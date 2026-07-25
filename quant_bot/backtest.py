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
        n_jobs=-1, verbosity=0,
    )
    model.fit(X, y)
    return model


def _select_universe(df_tickers: pd.DataFrame, year: int, month: int):
    mask = (df_tickers["date"].dt.year == year) & (df_tickers["date"].dt.month == month)
    if mask.sum() == 0:
        return None
    return df_tickers.loc[mask, "tickers"].iloc[0]


def run_backtest(features: pd.DataFrame, labels: pd.Series, price_df: pd.DataFrame,
                  df_tickers: pd.DataFrame, cfg: StrategyConfig):
    """Returns (monthly_returns: list[float], turnovers: list[float], months: list[Period])."""
    price_df = price_df.sort_index()
    months = pd.period_range(f"{cfg.start_year}-01", f"{cfg.end_year}-12", freq="M")

    monthly_returns, turnovers, periods = [], [], []
    prev_weights = pd.Series(dtype=float)
    capital = cfg.capital_eur

    for period in months:
        current_start = period.to_timestamp(how="start")
        prev_period = months[months < period].max()
        if pd.isna(prev_period):
            continue

        tickers_for_month = _select_universe(df_tickers, prev_period.year, prev_period.month)
        if not tickers_for_month:
            continue

        train_start = current_start - pd.DateOffset(years=cfg.train_window_years)
        train_mask = (
            (features.index.get_level_values("date") >= train_start)
            & (features.index.get_level_values("date") < current_start)
            & (features.index.get_level_values("ticker").isin(tickers_for_month))
        )
        month_dates = features.index.get_level_values("date")
        test_mask = (
            (month_dates >= current_start)
            & (month_dates < current_start + pd.offsets.MonthEnd(1))
            & (features.index.get_level_values("ticker").isin(tickers_for_month))
        )
        if train_mask.sum() < 100 or test_mask.sum() == 0:
            continue

        X_train, y_train = features[train_mask], labels.reindex(features[train_mask].index)
        X_test = features[test_mask]

        try:
            model = train_model(X_train, y_train, cfg)
            preds = model.predict(X_test)
        except ValueError:
            continue

        order = np.argsort(preds)[::-1]
        ordered_tickers = X_test.index.get_level_values("ticker")[order]
        top_n_tickers = list(dict.fromkeys(ordered_tickers))[:cfg.top_n]
        if len(top_n_tickers) == 0:
            continue

        # --- position sizing on trailing daily returns up to (not including) current_start ---
        hist_window = price_df.loc[:current_start].tail(126 + 1)
        hist_returns = hist_window.pct_change(fill_method=None).dropna(how="all")
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
