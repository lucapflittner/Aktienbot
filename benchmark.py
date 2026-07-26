"""Autoresearch benchmark harness (single, read-only file — see
.claude/skills/autoresearch/SKILL.md). Iteration edits quant_bot/*.py,
this file only measures. Prints `metric: <float>` = annualized Sharpe ratio
of the strategy's net monthly returns over the real, walk-forward-backtested
2018-2026 window. Also prints the full metric bundle and a buy-and-hold
reference line for context.

Usage: python benchmark.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from quant_bot import data, metrics
from quant_bot.backtest import buy_and_hold, run_backtest
from quant_bot.config import DEFAULT_CONFIG
from quant_bot.features import get_features_and_labels

RESULTS_DIR = Path(__file__).resolve().parent / "autoresearch"


def main():
    t0 = time.time()
    cfg = DEFAULT_CONFIG

    price_df = data.load_prices()
    df_tickers = data.load_universe(cfg.train_window_years, cfg.start_year)
    volume_df = data.load_volume() if cfg.include_volume_features else None
    features, labels = get_features_and_labels(price_df, cfg.label_horizon_days,
                                                volume_df, cfg.include_volume_features,
                                                cfg.rebalance_freq)

    monthly_returns, turnovers, periods = run_backtest(features, labels, price_df, df_tickers, cfg)
    if len(monthly_returns) == 0:
        print("metric: -999.0")
        print("ERROR: backtest produced zero months — harness or data problem", file=sys.stderr)
        sys.exit(1)

    periods_per_year = {"W": 52, "M": 12, "Q": 4, "A": 1, "Y": 1}.get(cfg.rebalance_freq, 12)
    m = metrics.summarize(monthly_returns, periods_per_year)
    bh_returns = buy_and_hold(price_df, df_tickers, cfg.start_year, cfg.end_year)
    bh = metrics.summarize(bh_returns)

    elapsed = time.time() - t0

    print(f"metric: {m['sharpe']:.4f}")
    print(f"cagr: {m['cagr']:.4f}")
    print(f"sortino: {m['sortino']:.4f}")
    print(f"calmar: {m['calmar']:.4f}")
    print(f"max_drawdown: {m['max_drawdown']:.4f}")
    print(f"annual_vol: {m['annual_vol']:.4f}")
    print(f"avg_turnover: {np.mean(turnovers):.4f}")
    print(f"n_months: {m['n_periods']}")
    print(f"elapsed_sec: {elapsed:.1f}")
    print(f"benchmark_sharpe (buy&hold): {bh['sharpe']:.4f}")
    print(f"benchmark_cagr (buy&hold): {bh['cagr']:.4f}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "last_run.json").write_text(json.dumps({
        "config": cfg.as_dict(),
        "metrics": m,
        "buy_and_hold": bh,
        "avg_turnover": float(np.mean(turnovers)),
        "elapsed_sec": elapsed,
    }, indent=2))

    sys.exit(0)


if __name__ == "__main__":
    main()
