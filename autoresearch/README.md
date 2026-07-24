# autoresearch tracking folder

State for the `/autoresearch` skill (see `.claude/skills/autoresearch/SKILL.md`).

- `results.tsv` — one row per iteration: commit hash, metric (annualized Sharpe
  of the 2018-2026 walk-forward backtest), status (baseline/keep/discard/
  discard-regression/crash), one-sentence description of the change.
- `.regression-baseline` — pass-count from `regression_check.py` before any
  iteration touched the code. An iteration that drops below this count is
  auto-discarded regardless of its Sharpe.
- `last_run.json` — full metric bundle from the most recent `benchmark.py`
  run (gitignored, regenerated every run).
- Corpus: real S&P 500 daily closes 2007-04-25 → 2026-04-10 for 884 historical
  constituents (`stock_portfoliomanagement_app/price_df.xlsx`, cached as
  parquet in `quant_bot/cache/`) plus the real historical index-membership
  list (`S&P 500 Historical Components & Changes.csv`, from fja05680/sp500).
  No synthetic data is used for the actual metric — only `regression_check.py`
  uses synthetic prices, and only to test mechanical properties (no
  look-ahead, valid weights) that don't need real market data.
- Goal on file: maximize `metric` (Sharpe ratio) of `quant_bot/config.py`'s
  `DEFAULT_CONFIG`, long-only, monthly-rebalanced, net of transaction costs,
  without dropping below the regression baseline.
