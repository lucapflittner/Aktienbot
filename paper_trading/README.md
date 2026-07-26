# paper_trading

Forward paper-trading test for `quant_bot`'s current `DEFAULT_CONFIG`. Runs
once a day via a GitHub Actions scheduled workflow (`.github/workflows/
paper_trading.yml`, 22:00 UTC daily) — hosted in the cloud, no local machine
needs to be running. Applies the exact same trained-model + weighting +
cost-model pipeline as `benchmark.py` to genuinely new daily closes that
autoresearch never saw or optimized against.

The workflow checks out the repo, runs `run_daily.py`, then commits the
updated `state.json` / `nav_log.csv` / `live_prices.parquet` back to the repo
itself — that's the persistence mechanism, there's no external database.
(A previous version of this ran on a local Windows scheduled task; that's been
removed in favor of this, to avoid two independent paper portfolios diverging.)

**One-time manual step required:** GitHub Actions' default `GITHUB_TOKEN` needs
write access to push commits. In the repo's GitHub page: Settings → Actions →
General → "Workflow permissions" → select "Read and write permissions" → Save.
Without this the workflow will run but fail on the final push step.

**Why this exists:** the backtest's headline numbers came from trying 30+
config variants and keeping the best on one fixed historical window (2018-2026)
— a classic setup for overfitting. This system exists to answer, honestly and
without fabricated data, whether the picked config (`top_n=5`,
`label_horizon_days=42`, inverse-vol weighting, realistic costs) still works
going forward on data nobody selected against.

## How it works

- `live_data.py` fetches real daily closes via yfinance for the current S&P 500
  universe (most recent snapshot in `S&P 500 Historical Components & Changes.csv`)
  and appends them to `live_prices.parquet` — the original historical
  `price_df.xlsx` is never touched.
- `engine.py` walks forward through every new trading day, one at a time:
  marks the paper portfolio to market daily, and on the first trading day of
  each new month, retrains on `quant_bot`'s exact `train_model` using only data
  strictly before that day, ranks the current universe, and rebalances —
  charging the same `spread_bps` + `flat_fee_per_trade_eur` cost model as the
  backtest. A parallel equal-weight buy-and-hold paper portfolio is tracked for
  comparison.
- `run_daily.py` is the entry point the workflow calls; safe to run more than
  once a day or after a gap (it only processes days it hasn't seen yet) --
  also runnable locally any time: `"C:\Users\lucap\anaconda3\envs\tf-gpu\python.exe" -m paper_trading.run_daily`
- `report.py` prints current NAV, cumulative/annualized return, and holdings —
  run it anytime: `"C:\Users\lucap\anaconda3\envs\tf-gpu\python.exe" -m paper_trading.report`
  (pull latest first: `git pull`, since the state now lives in the repo).

## State (tracked in git — this repo IS the database)

- `state.json` — cash, share holdings (bot + benchmark), last-processed date.
- `nav_log.csv` — one row per trading day: NAV and cumulative return, both books.
- `live_prices.parquet` — accumulated live closes since this system started.
- `run_daily.log` — gitignored (transient); GitHub Actions' own run logs are
  the durable record of what happened on the cloud side.

## Known limitations

- Universe membership uses the latest static snapshot in the S&P 500 CSV —
  real index reconstitutions between refreshes of that file aren't reflected.
- A handful of tickers fail to fetch via yfinance (`BK`, `CTRA`, `HOLX`, `DAY`
  as of this writing — possibly a transient Yahoo issue; `BRK.B`/`BF.B` aren't
  in the historical dataset at all due to dot/dash ticker-symbol mismatches).
  Missing names are simply excluded from that day's picks.
- Costs are simulated identically to the backtest (spread_bps + flat fee
  against a compounding capital_eur) — still not real broker execution, slippage,
  or taxes.
- GitHub's cron scheduling isn't second-precise and can be delayed by minutes
  to (rarely) longer under platform load -- fine for a once-daily job.

## Removing / pausing

Disable without deleting: repo Settings → Actions → General → disable, or
delete `.github/workflows/paper_trading.yml`. To run locally again instead,
re-add the Windows scheduled task:
```
schtasks /Create /TN "AktienbotPaperTrading" /TR "G:\Programmierzeugs\Aktienbot\paper_trading\run_daily.bat" /SC DAILY /ST 23:00 /F
```
