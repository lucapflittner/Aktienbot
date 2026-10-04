"""Walk-forward monthly backtest: train on a real rolling window, predict next
month's cross-section, pick a basket, size it, realize the return next month.

No look-ahead: at month t the model only ever sees (a) the S&P 500 membership
list as of month t-1, (b) features built from prices up to the last trading
day before t, and (c) training labels whose 21-day-forward window closes
before t. Test features are the first trading day of month t itself.
"""
import numpy as np
import pandas as pd
from xgboost import XGBRegressor, XGBRanker

from .config import StrategyConfig
from .weighting import SCHEMES, volatility_target_scale


def train_model(X: pd.DataFrame, y: pd.Series, cfg: StrategyConfig):
    mask = y.notna() & np.isfinite(y)
    X, y = X[mask], y[mask]
    if len(X) == 0:
        raise ValueError("No valid training data")

    if cfg.rank_objective:
        # group by date so pairwise ranking compares tickers within the same month
        dates = X.index.get_level_values("date")
        order = np.argsort(dates.values, kind="stable")
        X, y = X.iloc[order], y.iloc[order]
        groups = pd.Series(dates[order]).value_counts(sort=False).sort_index()
        # rank labels must be ordinal ints; use cross-sectional return rank per date
        rank_y = y.groupby(X.index.get_level_values("date")).rank(method="first").astype(int)
        model = XGBRanker(
            n_estimators=cfg.model_n_estimators, max_depth=cfg.model_max_depth,
            learning_rate=cfg.model_learning_rate, objective="rank:pairwise", n_jobs=-1,
        )
        model.fit(X, rank_y, group=groups.values)
        return model

    model = XGBRegressor(
        n_estimators=cfg.model_n_estimators, max_depth=cfg.model_max_depth,
        learning_rate=cfg.model_learning_rate, objective="reg:squarederror",
        subsample=cfg.model_subsample, colsample_bytree=cfg.model_colsample_bytree,
        random_state=0, n_jobs=-1, verbosity=0,
    )
    model.fit(X, y)
    return model


def select_top_n_with_corr_cap(ranked_tickers: list, hist_returns: pd.DataFrame,
                                top_n: int, corr_cap: float) -> list:
    """Greedily build a top_n basket from a predicted-return-ranked candidate
    list: walk down the ranking and accept a candidate unless its trailing
    return correlation (over the SAME point-in-time hist_returns window used
    for inverse_vol/HRP weighting) to any name already accepted exceeds
    corr_cap, in which case skip it and move to the next candidate. This
    changes WHICH names get picked (unlike HRP/inverse_vol, which only decide
    sizing after the basket is already fixed), aiming to stop the basket from
    concentrating in one correlated sector/factor move.

    Edge case: if the ranked list is exhausted before top_n slots are filled
    (every remaining candidate was too correlated to something already
    picked), relax the cap and backfill with the next-best skipped
    candidates rather than returning a smaller-than-top_n basket.
    """
    candidates = [t for t in ranked_tickers if t in hist_returns.columns]
    corr = hist_returns[candidates].corr() if candidates else pd.DataFrame()

    selected, skipped = [], []
    for t in ranked_tickers:
        if len(selected) >= top_n:
            break
        if t not in corr.columns:
            # no usable return history for this ticker (e.g. new listing) --
            # can't evaluate its correlation, so accept it directly.
            selected.append(t)
            continue
        too_correlated = any(
            pd.notna(corr.loc[t, s]) and corr.loc[t, s] > corr_cap
            for s in selected if s in corr.columns
        )
        if too_correlated:
            skipped.append(t)
        else:
            selected.append(t)

    if len(selected) < top_n:
        for t in skipped:
            if len(selected) >= top_n:
                break
            selected.append(t)

    return selected[:top_n]


def _select_universe(df_tickers: pd.DataFrame, year: int, month: int):
    mask = (df_tickers["date"].dt.year == year) & (df_tickers["date"].dt.month == month)
    if mask.sum() == 0:
        return None
    return df_tickers.loc[mask, "tickers"].iloc[0]


def run_backtest(features: pd.DataFrame, labels: pd.Series, price_df: pd.DataFrame,
                  df_tickers: pd.DataFrame, cfg: StrategyConfig):
    """Returns (monthly_returns: list[float], turnovers: list[float], months: list[Period])."""
    price_df = price_df.sort_index()
    months = pd.period_range(f"{cfg.start_year}-01-01", f"{cfg.end_year}-12-31", freq=cfg.rebalance_freq)

    monthly_returns, turnovers, periods = [], [], []
    prev_weights = pd.Series(dtype=float)
    capital = cfg.capital_eur
    model = None
    last_retrain_bucket = None
    retrain_freq = cfg.retrain_freq or cfg.rebalance_freq

    for period in months:
        current_start = period.to_timestamp(how="start")
        prev_period = months[months < period].max()
        if pd.isna(prev_period):
            continue

        tickers_for_month = _select_universe(df_tickers, prev_period.year, prev_period.month)
        if not tickers_for_month:
            continue

        period_end_exclusive = (period + 1).to_timestamp(how="start")
        month_dates = features.index.get_level_values("date")
        test_mask = (
            (month_dates >= current_start)
            & (month_dates < period_end_exclusive)
            & (features.index.get_level_values("ticker").isin(tickers_for_month))
        )
        if test_mask.sum() == 0:
            continue
        X_test = features[test_mask]

        # retrain only when crossing into a new retrain_freq bucket (identical to
        # retraining every period when retrain_freq is None/== rebalance_freq);
        # otherwise reuse the existing model and just re-score this period's
        # fresh features, so a finer rebalance_freq doesn't force a full refit.
        retrain_bucket = current_start.to_period(retrain_freq)
        need_retrain = model is None or retrain_bucket != last_retrain_bucket
        if need_retrain:
            train_start = current_start - pd.DateOffset(months=round(cfg.train_window_years * 12))
            train_mask = (
                (features.index.get_level_values("date") >= train_start)
                & (features.index.get_level_values("date") < current_start)
                & (features.index.get_level_values("ticker").isin(tickers_for_month))
            )
            if train_mask.sum() < 100:
                continue
            X_train, y_train = features[train_mask], labels.reindex(features[train_mask].index)
            try:
                model = train_model(X_train, y_train, cfg)
            except ValueError:
                continue
            last_retrain_bucket = retrain_bucket

        try:
            preds = model.predict(X_test)
        except ValueError:
            continue

        order = np.argsort(preds)[::-1]
        ordered_tickers = X_test.index.get_level_values("ticker")[order]
        ranked_tickers = list(dict.fromkeys(ordered_tickers))

        # --- trailing daily returns up to (not including) current_start; reused for
        # both the optional correlation-cap selection below and inverse_vol/HRP sizing ---
        hist_window = price_df.loc[:current_start].tail(126 + 1)
        hist_returns = hist_window.pct_change(fill_method=None).dropna(how="all")

        if cfg.model_corr_cap is not None:
            top_n_tickers = select_top_n_with_corr_cap(ranked_tickers, hist_returns,
                                                         cfg.top_n, cfg.model_corr_cap)
        else:
            top_n_tickers = ranked_tickers[:cfg.top_n]
        if len(top_n_tickers) == 0:
            continue

        weight_fn = SCHEMES[cfg.weighting]
        weights = weight_fn(hist_returns, top_n_tickers)

        # --- turnover vs previous month's basket, for transaction costs ---
        all_names = weights.index.union(prev_weights.index)
        weight_deltas = (weights.reindex(all_names, fill_value=0.0)
                          - prev_weights.reindex(all_names, fill_value=0.0))
        turnover = float(weight_deltas.abs().sum())
        num_trades = int((weight_deltas.abs() > 1e-6).sum())
        turnovers.append(turnover)
        prev_weights = weights

        # --- realized return over the holding month ---
        month_end = (period + 1).to_timestamp(how="start") - pd.Timedelta(days=1)
        try:
            start_prices = price_df.loc[:current_start, top_n_tickers].iloc[-1]
            end_prices = price_df.loc[:month_end, top_n_tickers].iloc[-1]
        except (KeyError, IndexError):
            continue

        valid = start_prices.notna() & end_prices.notna()
        if valid.sum() == 0:
            continue
        rets = end_prices[valid] / start_prices[valid] - 1
        w = weights.reindex(rets.index).fillna(0.0)
        w = w / w.sum() if w.sum() > 0 else w
        raw_return = float((rets * w).sum())

        leverage = 1.0
        if cfg.vol_target is not None and len(hist_returns) > 0:
            basket_daily = (hist_returns[top_n_tickers].fillna(0.0) * weights.reindex(top_n_tickers).fillna(0.0)).sum(axis=1)
            leverage = volatility_target_scale(basket_daily, cfg.vol_target, cfg.vol_target_lookback)

        spread_cost = (cfg.spread_bps / 10_000.0) * turnover
        flat_fee_cost = (num_trades * cfg.flat_fee_per_trade_eur) / capital if capital > 0 else 0.0
        net_return = raw_return * leverage - spread_cost - flat_fee_cost

        monthly_returns.append(net_return)
        periods.append(period)
        capital *= (1.0 + net_return)

    return monthly_returns, turnovers, periods


def buy_and_hold(price_df: pd.DataFrame, df_tickers: pd.DataFrame, start_year: int, end_year: int):
    price_df = price_df.sort_index()
    months = pd.period_range(f"{start_year}-01", f"{end_year}-12", freq="M")
    monthly_returns = []

    for period in months:
        start = period.to_timestamp(how="start")
        end = (period + 1).to_timestamp(how="start") - pd.Timedelta(days=1)
        tickers = _select_universe(df_tickers, start.year, start.month)
        if not tickers:
            continue
        tickers = [t for t in tickers if t in price_df.columns]
        if not tickers:
            continue
        try:
            start_prices = price_df.loc[:start, tickers].iloc[-1]
            end_prices = price_df.loc[:end, tickers].iloc[-1]
        except (KeyError, IndexError):
            continue
        valid = start_prices.notna() & end_prices.notna()
        if valid.sum() == 0:
            continue
        rets = end_prices[valid] / start_prices[valid] - 1
        monthly_returns.append(float(rets.mean()))

    return monthly_returns
