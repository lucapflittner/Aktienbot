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


def test_tiny_backtest_runs():
    prices = make_synthetic_prices(n_days=900, n_tickers=15)
    tickers = list(prices.columns)
    dates = prices.index
    df_tickers = pd.DataFrame({
        "date": [dates[0], dates[300], dates[600]],
        "tickers": [tickers, tickers, tickers],
    })

    features = engineer_features(prices)
    future_returns = prices.pct_change(21, fill_method=None).shift(-21)
    labels = future_returns.stack().reset_index()
    labels.columns = ["date", "ticker", "future_return"]
    labels = labels.set_index(["date", "ticker"])["future_return"]
    common = features.index.intersection(labels.index)
    features, labels = features.loc[common], labels.loc[common]

    cfg = StrategyConfig(start_year=dates[400].year, end_year=dates[-1].year,
                          train_window_years=1, top_n=3)
    monthly_returns, turnovers, periods = run_backtest(features, labels, prices, df_tickers, cfg)

    check("tiny backtest produced some months", len(monthly_returns) > 0)
    check("tiny backtest returns are finite", np.all(np.isfinite(monthly_returns)))
    check("tiny backtest returns are sane (no -100%/month)", all(r > -1.0 for r in monthly_returns))


if __name__ == "__main__":
    test_no_lookahead()
    test_weighting_schemes_valid()
    test_tiny_backtest_runs()
    print(f"passed: {CHECKS_PASSED}")
    sys.exit(0)
