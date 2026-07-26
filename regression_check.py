"""Regression gate for the autoresearch loop (Phase D). No pytest dependency
by design — plain asserts, run in a few seconds so every iteration can afford
it. Exits 0 and prints `passed: <n>` iff every check holds; the autoresearch
skill compares that count against autoresearch/.regression-baseline.

Checks:
  1. No look-ahead: perturbing a price AFTER date t must not change any
     feature row computed AT date t.
  2. Weighting schemes return long-only weights that sum to 1.
  3. A tiny end-to-end backtest slice runs without crashing and produces
     finite, sane returns.
"""
import sys

import numpy as np
import pandas as pd

from quant_bot.features import engineer_features
from quant_bot.weighting import SCHEMES
from quant_bot.backtest import run_backtest
from quant_bot.config import StrategyConfig

CHECKS_PASSED = 0


def check(name, condition):
    global CHECKS_PASSED
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        raise SystemExit(f"regression check failed: {name}")
    CHECKS_PASSED += 1


def make_synthetic_prices(n_days=400, n_tickers=6, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    tickers = [f"T{i}" for i in range(n_tickers)]
    prices = 100 * np.cumprod(1 + rng.normal(0.0003, 0.02, size=(n_days, n_tickers)), axis=0)
    return pd.DataFrame(prices, index=dates, columns=tickers)


def test_no_lookahead():
    prices = make_synthetic_prices()
    feat_a = engineer_features(prices)

    cutoff = prices.index[250]
    perturbed = prices.copy()
    perturbed.loc[perturbed.index > cutoff] *= 1.5  # only future prices change
    feat_b = engineer_features(perturbed)

    idx_before = feat_a.index.get_level_values("date") <= cutoff
    before_a = feat_a[idx_before].sort_index()
    before_b = feat_b[idx_before].sort_index()
    common = before_a.index.intersection(before_b.index)
    check(
        "features at/before cutoff are unchanged when only future prices move",
        np.allclose(before_a.loc[common].values, before_b.loc[common].values, equal_nan=True),
    )


def test_weighting_schemes_valid():
    prices = make_synthetic_prices()
    hist_returns = prices.pct_change(fill_method=None).dropna()
    tickers = list(prices.columns)[:5]
    for name, fn in SCHEMES.items():
        w = fn(hist_returns, tickers)
        check(f"weighting '{name}' sums to 1", abs(w.sum() - 1.0) < 1e-6)
        check(f"weighting '{name}' is long-only", (w >= -1e-9).all())


def _run_tiny_backtest(cfg: StrategyConfig, prices: pd.DataFrame, df_tickers: pd.DataFrame):
    features = engineer_features(prices, resample_freq=cfg.rebalance_freq)
    future_returns = prices.pct_change(cfg.label_horizon_days, fill_method=None).shift(-cfg.label_horizon_days)
    labels = future_returns.stack().reset_index()
    labels.columns = ["date", "ticker", "future_return"]
    labels = labels.set_index(["date", "ticker"])["future_return"]
    return run_backtest(features, labels, prices, df_tickers, cfg)


def test_tiny_backtest_runs():
    # n_days=900 (~3.5y) with a membership snapshot every ~21 trading days (not
    # just 3 fixed dates) so _select_universe's exact (year, month) match can
    # find a hit regardless of rebalance_freq (W/M/Q/Y all exercised below) --
    # a sparser snapshot table happens to work for monthly by luck but starves
    # quarterly/yearly of any matching month, which is a test artifact, not a
    # real limitation of those frequencies on the actual 19-year corpus.
    prices = make_synthetic_prices(n_days=900, n_tickers=15)
    tickers = list(prices.columns)
    dates = prices.index
    snapshot_dates = dates[::21]
    df_tickers = pd.DataFrame({
        "date": snapshot_dates,
        "tickers": [tickers] * len(snapshot_dates),
    })

    # Explicitly pins rebalance_freq/label_horizon_days rather than inheriting
    # StrategyConfig's class defaults -- this is meant to be a fast, generic
    # smoke test independent of whatever frequency the current production
    # config happens to be experimenting with (that's what the dedicated
    # multi-frequency test below covers); inheriting "whatever's default now"
    # previously made this take 45s+ once weekly became the default, since
    # dates[400]-to-end spans multiple years of weekly periods.
    cfg = StrategyConfig(start_year=dates[400].year, end_year=dates[-1].year,
                          train_window_years=1, top_n=3,
                          rebalance_freq="M", label_horizon_days=21)
    monthly_returns, turnovers, periods = _run_tiny_backtest(cfg, prices, df_tickers)

    check("tiny backtest produced some months", len(monthly_returns) > 0)
    check("tiny backtest returns are finite", np.all(np.isfinite(monthly_returns)))
    check("tiny backtest returns are sane (no -100%/month)", all(r > -1.0 for r in monthly_returns))


def test_tiny_backtest_runs_at_every_rebalance_freq():
    # W/M/Q share the same small dataset as test_tiny_backtest_runs (fast).
    # model_n_estimators is cut way down from production's 300 -- this checks
    # mechanics (does it run, are outputs sane), not model quality, and
    # per-period XGBoost fit/n_jobs=-1 overhead otherwise adds up across many
    # weekly periods.
    prices = make_synthetic_prices(n_days=900, n_tickers=15)
    tickers = list(prices.columns)
    dates = prices.index
    snapshot_dates = dates[::21]
    df_tickers = pd.DataFrame({
        "date": snapshot_dates,
        "tickers": [tickers] * len(snapshot_dates),
    })
    # train_window_years=2 (not 1) so quarterly clears the >=100-row threshold
    # with only 15 tickers (2yr x 4qtrs x 15 = 120); W/M clear it trivially too.
    # eval_start == eval_end (a single calendar year, ~52/12/4 periods) --
    # period_range is built from these .year values alone, so a wider gap
    # here silently multiplies the period count (and runtime) regardless of
    # how close the underlying index positions are.
    eval_start = eval_end = dates[700].year
    for freq, label_days in [("W", 10), ("M", 21), ("Q", 63)]:
        cfg = StrategyConfig(start_year=eval_start, end_year=eval_end,
                              train_window_years=2, top_n=3, model_n_estimators=10,
                              rebalance_freq=freq, label_horizon_days=label_days)
        monthly_returns, turnovers, periods = _run_tiny_backtest(cfg, prices, df_tickers)
        check(f"tiny backtest produced some periods at rebalance_freq={freq}", len(monthly_returns) > 0)

    # Yearly needs enough rows per training window (>=100, same threshold
    # run_backtest uses in production) even with only 1 row/ticker/year --
    # more tickers and a longer synthetic series than the above, so this stays
    # a fair mechanical check instead of an artifact of too little synthetic
    # data (train_window_years=3 x 40 tickers = 120 rows/year, just clearing
    # the threshold). Kept as its own smaller dataset+window (not reused for
    # W/M/Q above) since a 2500-day series makes weekly resampling alone take
    # ~15s -- wasteful when W/M/Q only need the small dataset.
    big_prices = make_synthetic_prices(n_days=2500, n_tickers=40, seed=11)
    big_tickers = list(big_prices.columns)
    big_dates = big_prices.index
    big_snapshots = big_dates[::21]
    big_df_tickers = pd.DataFrame({
        "date": big_snapshots,
        "tickers": [big_tickers] * len(big_snapshots),
    })
    # must span >=2 distinct calendar years, or Y gets exactly 1 period and 0 valid (no prev_period)
    y_eval_start, y_eval_end = big_dates[-380].year, big_dates[-1].year
    cfg_y = StrategyConfig(start_year=y_eval_start, end_year=y_eval_end,
                            train_window_years=3, top_n=3, model_n_estimators=10,
                            rebalance_freq="Y", label_horizon_days=252)
    monthly_returns, turnovers, periods = _run_tiny_backtest(cfg_y, big_prices, big_df_tickers)
    check("tiny backtest produced some periods at rebalance_freq=Y", len(monthly_returns) > 0)


if __name__ == "__main__":
    test_no_lookahead()
    test_weighting_schemes_valid()
    test_tiny_backtest_runs()
    test_tiny_backtest_runs_at_every_rebalance_freq()
    print(f"passed: {CHECKS_PASSED}")
    sys.exit(0)
