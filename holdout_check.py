"""Locked-holdout check (companion to benchmark.py — see
.claude/skills/autoresearch/SKILL.md). NOT part of the autoresearch loop:
never used to decide keep/discard, never run every iteration. It exists to
answer, honestly, whether a config that won on the 2018-2023 research window
(what benchmark.py measures) also holds up on 2024-2026 data that no
experiment in results.tsv has ever been tuned against.

Run this sparingly (e.g. before trusting a big keep, or every ~10 iterations
as a sanity check) — checking it every iteration would just turn the holdout
into a second research window and defeat the point. If a config's holdout
Sharpe diverges sharply from its research-window Sharpe, that is itself the
finding: it means the research-window result doesn't generalize, and the
right response is to prefer simpler/more conservative configs going forward,
not to start tuning against the holdout number.

Usage: python holdout_check.py
"""
import dataclasses
import sys
import time

import numpy as np

from quant_bot import data, metrics
from quant_bot.backtest import buy_and_hold, run_backtest
from quant_bot.config import DEFAULT_CONFIG
from quant_bot.features import get_features_and_labels

HOLDOUT_START_YEAR = 2024
HOLDOUT_END_YEAR = 2026


def main():
    t0 = time.time()
    cfg = dataclasses.replace(DEFAULT_CONFIG, start_year=HOLDOUT_START_YEAR, end_year=HOLDOUT_END_YEAR)

    price_df = data.load_prices()
    df_tickers = data.load_universe(cfg.train_window_years, cfg.start_year)
    volume_df = data.load_volume() if cfg.include_volume_features else None
    features, labels = get_features_and_labels(price_df, cfg.label_horizon_days,
                                                volume_df, cfg.include_volume_features,
                                                cfg.rebalance_freq)

    period_returns, turnovers, periods = run_backtest(features, labels, price_df, df_tickers, cfg)
    if len(period_returns) == 0:
        print("metric: -999.0")
        print("ERROR: holdout backtest produced zero periods", file=sys.stderr)
        sys.exit(1)

    periods_per_year = {"W": 52, "M": 12, "Q": 4, "A": 1, "Y": 1}.get(cfg.rebalance_freq, 12)
    m = metrics.summarize(period_returns, periods_per_year)
    bh_returns = buy_and_hold(price_df, df_tickers, cfg.start_year, cfg.end_year)
    bh = metrics.summarize(bh_returns)

    elapsed = time.time() - t0

    print(f"holdout_window: {cfg.start_year}-{cfg.end_year}")
    print(f"metric: {m['sharpe']:.4f}")
    print(f"cagr: {m['cagr']:.4f}")
    print(f"sortino: {m['sortino']:.4f}")
    print(f"calmar: {m['calmar']:.4f}")
    print(f"max_drawdown: {m['max_drawdown']:.4f}")
    print(f"annual_vol: {m['annual_vol']:.4f}")
    print(f"avg_turnover: {np.mean(turnovers):.4f}")
    print(f"n_periods: {m['n_periods']}")
    print(f"elapsed_sec: {elapsed:.1f}")
    print(f"benchmark_sharpe (buy&hold): {bh['sharpe']:.4f}")
    print(f"benchmark_cagr (buy&hold): {bh['cagr']:.4f}")

    sys.exit(0)


if __name__ == "__main__":
    main()
