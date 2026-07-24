# The benchmark harness (project-specific)

Karpathy's autoresearch generically asks you to build a benchmark harness
from scratch per goal. For this project it already exists — this file is
what a generic "Phase A-E gate" write-up would have produced, pre-filled.

## Corpus (Phase A — already satisfied, real data)

- **Prices:** `stock_portfoliomanagement_app/price_df.xlsx` — real yfinance
  daily closes, 2007-04-25 to 2026-04-10, 884 historical S&P 500
  constituents (includes delisted/renamed tickers like `ABKFQ`, `CVNA`-era
  predecessors, etc.). Cached as parquet in `quant_bot/cache/prices.parquet`
  for ~35s → ~0.2s load time; regenerated automatically if the xlsx is newer.
- **Universe membership:** `S&P 500 Historical Components & Changes.csv`
  (fja05680/sp500 on GitHub) — real historical index membership by date, used
  so the backtest only ever picks from stocks that were *actually* in the
  index at that time (survivorship-bias aware).
- Refresh the corpus only by re-running the download logic in
  `stock_portfoliomanagement_app/app.py` (`download_all_tickers_close`) if
  the user asks for more recent data — don't hand-edit the cached files.

## The harness itself (Phase B)

`benchmark.py` at the repo root:
- loads prices + universe (`quant_bot.data`)
- computes/loads cached features + labels (`quant_bot.features`)
- runs the walk-forward backtest (`quant_bot.backtest.run_backtest`) using
  `quant_bot.config.DEFAULT_CONFIG`
- prints `metric: <sharpe>` (this is the line the loop parses) plus `cagr:`,
  `sortino:`, `calmar:`, `max_drawdown:`, `annual_vol:`, `avg_turnover:`,
  `n_months:`, `elapsed_sec:`, and a buy-and-hold reference pair for context
- writes the full bundle to `autoresearch/last_run.json` (gitignored)
- exits 1 and prints `metric: -999.0` if the backtest produces zero months
  (config broke a filter somewhere — investigate before retrying)

**Do not edit `benchmark.py` casually.** If a genuine harness change is
needed (new metric, different eval window), make it a separate commit
prefixed `harness:` — never bundle a harness edit with a strategy
experiment, or you can't tell whether a metric change came from the strategy
or from redefining the ruler.

## Baseline (Phase C — already captured)

`autoresearch/results.tsv` iteration 0: Sharpe 0.6515, CAGR 16.5%, MaxDD
-26.1%, from an XGBoost regressor (`reg:squarederror`) picking the top-10
predicted names each month, equal-weighted, 3-year rolling training window,
21-day-forward label, 10bps transaction cost, 2018-2026 walk-forward. For
comparison, buy-and-hold the same monthly S&P 500 universe over the same
window: Sharpe 0.689, CAGR 12.0% (see `benchmark.py` output — printed every
run, not logged to `results.tsv`, since it isn't the thing being optimized).

## Regression gate (Phase D — already wired)

`regression_check.py`, no pytest dependency (not installed in the project's
conda env — see below). ~10 mechanical assertions: no look-ahead bias
(perturb-future-prices test), every weighting scheme in
`quant_bot/weighting.SCHEMES` sums to 1 and is long-only, and a tiny
synthetic end-to-end backtest runs and returns finite, sane numbers. Current
baseline pass count: 10 (`autoresearch/.regression-baseline`). If you
add checks, only raise the baseline count once they're passing on `main`,
not mid-experiment.

## Environment

The repo has no venv; the working Python is the conda env `tf-gpu`:
```
"/c/Users/lucap/anaconda3/envs/tf-gpu/python.exe" benchmark.py
"/c/Users/lucap/anaconda3/envs/tf-gpu/python.exe" regression_check.py
```
Bare `python`/`python3` on PATH resolve to an unrelated Python 3.8 with no
pandas installed — always use the full conda env path above.

## Enforcement refusals

Refuse to start (and say why) if any of:
- `autoresearch/results.tsv` has no `baseline` row
- `autoresearch/.regression-baseline` is missing
- `benchmark.py` prints anything other than a `metric: <float>` line
- someone asks to fabricate price history instead of using the real corpus
  above (e.g. to "fill gaps" or "extend the backtest" with made-up numbers)
