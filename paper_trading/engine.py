"""Forward paper-trading engine: applies quant_bot's exact trained-model +
weighting + cost-model pipeline to genuinely new (never backtested-on) daily
closes, one real calendar day at a time. No look-ahead: at any processed date
D, only prices strictly before D are used for training, matching
quant_bot.backtest.run_backtest's own discipline.

This is deliberately NOT a backtest re-run -- it's meant to accumulate a real,
un-fabricated forward track record starting from whenever this system first
ran, to check whether autoresearch's picked config holds up outside the
window it was selected on.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_bot.backtest import train_model
from quant_bot.config import DEFAULT_CONFIG
from quant_bot.features import engineer_features, create_labels
from quant_bot.weighting import SCHEMES
from paper_trading.live_data import load_combined_prices, get_current_universe

STATE_PATH = Path(__file__).resolve().parent / "state.json"
NAV_LOG_PATH = Path(__file__).resolve().parent / "nav_log.csv"


def _default_state(cfg):
    return {
        "capital_eur": cfg.capital_eur,
        "inception_date": None,
        "last_processed_date": None,
        "last_rebalance_month": None,
        "bot": {"cash": cfg.capital_eur, "shares": {}},
        "bench": {"cash": cfg.capital_eur, "shares": {}},
        "trade_log": [],
    }


def load_state(cfg=DEFAULT_CONFIG):
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return _default_state(cfg)


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _price_asof(prices: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    """Latest known close per ticker as of `date`, forward-filled across gaps
    (holidays, individual-name halts) so a held position always marks."""
    return prices.loc[:date].ffill().iloc[-1]


def _mark_to_market(shares: dict, cash: float, price_row: pd.Series) -> float:
    value = cash
    for ticker, n in shares.items():
        p = price_row.get(ticker)
        if p is not None and pd.notna(p):
            value += n * p
    return float(value)


def _shares_from_weights(weights: pd.Series, nav: float, price_row: pd.Series) -> dict:
    shares = {}
    for ticker, w in weights.items():
        p = price_row.get(ticker)
        if p is None or pd.isna(p) or p <= 0:
            continue
        shares[ticker] = (w * nav) / p
    return shares


def _weights_from_shares(shares: dict, price_row: pd.Series) -> pd.Series:
    values = {t: n * price_row.get(t, np.nan) for t, n in shares.items()}
    s = pd.Series(values, dtype=float).dropna()
    total = s.sum()
    return s / total if total > 0 else s


def _rebalance_bot(cfg, features: pd.DataFrame, labels: pd.Series, prices: pd.DataFrame,
                    D: pd.Timestamp, state: dict) -> dict:
    # engineer_features resamples to one row per ticker per rebalance period
    # (cfg.rebalance_freq), dated at that period's first trading day -- NOT at
    # today's date D (D may be any day within the period, e.g. the first run
    # of this system starting mid-period). Find that anchor date so test_mask
    # actually matches real feature rows, then execute the resulting trade at
    # D's real closing price.
    feature_dates = features.index.get_level_values("date")
    this_period_dates = feature_dates[feature_dates.to_period(cfg.rebalance_freq) == D.to_period(cfg.rebalance_freq)]
    if len(this_period_dates) == 0:
        return {"skipped": "no feature row for this period yet"}
    month_anchor = this_period_dates.min()

    train_start = month_anchor - pd.DateOffset(years=cfg.train_window_years)
    train_mask = (
        (feature_dates >= train_start)
        & (feature_dates < month_anchor)
    )
    test_mask = feature_dates == month_anchor

    if train_mask.sum() < 100 or test_mask.sum() == 0:
        return {"skipped": "insufficient train/test data"}

    X_train = features[train_mask]
    y_train = labels.reindex(X_train.index)
    X_test = features[test_mask]

    model = train_model(X_train, y_train, cfg)
    preds = model.predict(X_test)
    order = np.argsort(preds)[::-1]
    ranked_tickers = X_test.index.get_level_values("ticker")[order]
    top_n_tickers = list(dict.fromkeys(ranked_tickers))[: cfg.top_n]
    if not top_n_tickers:
        return {"skipped": "no valid picks"}

    hist_window = prices.loc[:D].tail(127)
    hist_returns = hist_window.pct_change(fill_method=None).dropna(how="all")
    weight_fn = SCHEMES[cfg.weighting]
    target_weights = weight_fn(hist_returns, top_n_tickers)

    price_row = _price_asof(prices, D)
    nav_before = _mark_to_market(state["bot"]["shares"], state["bot"]["cash"], price_row)

    current_weights = _weights_from_shares(state["bot"]["shares"], price_row)
    all_names = target_weights.index.union(current_weights.index)
    deltas = (target_weights.reindex(all_names, fill_value=0.0)
              - current_weights.reindex(all_names, fill_value=0.0))
    turnover = float(deltas.abs().sum())
    num_trades = int((deltas.abs() > 1e-6).sum())

    spread_cost = (cfg.spread_bps / 10_000.0) * turnover * nav_before
    flat_cost = num_trades * cfg.flat_fee_per_trade_eur
    nav_after = nav_before - spread_cost - flat_cost

    new_shares = _shares_from_weights(target_weights, nav_after, price_row)
    spent = sum(n * price_row.get(t, 0.0) for t, n in new_shares.items())
    state["bot"]["shares"] = new_shares
    state["bot"]["cash"] = nav_after - spent

    return {
        "picks": top_n_tickers,
        "num_trades": num_trades,
        "turnover": turnover,
        "spread_cost_eur": spread_cost,
        "flat_cost_eur": flat_cost,
        "nav_before": nav_before,
        "nav_after": nav_after,
    }


def _rebalance_bench(prices: pd.DataFrame, universe: list, D: pd.Timestamp, state: dict):
    price_row = _price_asof(prices, D)
    valid = [t for t in universe if t in price_row.index and pd.notna(price_row[t])]
    if not valid:
        return
    nav = _mark_to_market(state["bench"]["shares"], state["bench"]["cash"], price_row)
    weights = pd.Series(1.0 / len(valid), index=valid)
    state["bench"]["shares"] = _shares_from_weights(weights, nav, price_row)
    state["bench"]["cash"] = 0.0


def process_new_days() -> list:
    """Walks forward through every real trading day fetched since the last
    run that hasn't been processed yet, one at a time, in order. Returns a
    list of per-day summary dicts (also appended to nav_log.csv)."""
    cfg = DEFAULT_CONFIG
    prices = load_combined_prices()
    universe = get_current_universe()
    universe = [t for t in universe if t in prices.columns]

    state = load_state(cfg)
    last_processed = pd.Timestamp(state["last_processed_date"]) if state["last_processed_date"] else None

    all_dates = prices.index
    if last_processed is not None:
        new_dates = all_dates[all_dates > last_processed]
    else:
        # Fresh start: the forward test begins NOW, not by replaying 19 years
        # of history day-by-day -- inception is the most recent available
        # trading day, and this first "day" is always a rebalance.
        new_dates = all_dates[-1:]
        state["last_rebalance_month"] = None
    if len(new_dates) == 0:
        return []

    universe_prices = prices[universe]
    features = engineer_features(universe_prices, resample_freq=cfg.rebalance_freq)
    # NB: do NOT intersect features with labels.index here. create_labels'
    # .stack() drops any row whose forward label isn't computable yet -- which
    # is every row from roughly the last label_horizon_days/21 months, i.e.
    # exactly the test row we need to predict for. Keep `features` full;
    # `labels.reindex(...)` below naturally yields NaN for rows without a
    # label, and train_model already drops NaN-labeled rows before fitting.
    labels = create_labels(universe_prices, cfg.label_horizon_days)

    summaries = []
    log_rows = []
    for D in new_dates:
        this_period = D.to_period(cfg.rebalance_freq)
        is_rebalance = (state["last_rebalance_month"] is None
                        or this_period > pd.Period(state["last_rebalance_month"], freq=cfg.rebalance_freq))

        detail = {"date": str(D.date()), "is_rebalance": is_rebalance}
        if is_rebalance:
            rb = _rebalance_bot(cfg, features, labels, universe_prices, D, state)
            detail.update(rb)
            if "skipped" not in rb:
                _rebalance_bench(universe_prices, universe, D, state)
                state["last_rebalance_month"] = str(this_period)
                state["trade_log"].append(detail)

        price_row = _price_asof(universe_prices, D)
        bot_nav = _mark_to_market(state["bot"]["shares"], state["bot"]["cash"], price_row)
        bench_nav = _mark_to_market(state["bench"]["shares"], state["bench"]["cash"], price_row)

        if state["inception_date"] is None:
            state["inception_date"] = str(D.date())

        log_rows.append({
            "date": str(D.date()),
            "bot_nav": bot_nav,
            "bot_cum_return": bot_nav / state["capital_eur"] - 1,
            "bench_nav": bench_nav,
            "bench_cum_return": bench_nav / state["capital_eur"] - 1,
            "is_rebalance": is_rebalance,
        })
        state["last_processed_date"] = str(D.date())
        summaries.append(detail)

    save_state(state)

    log_df = pd.DataFrame(log_rows)
    if NAV_LOG_PATH.exists():
        existing = pd.read_csv(NAV_LOG_PATH)
        log_df = pd.concat([existing, log_df], ignore_index=True)
    log_df.to_csv(NAV_LOG_PATH, index=False)

    return summaries
