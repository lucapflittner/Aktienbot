# paper_trading

Forward paper-trading test for `quant_bot`'s current `DEFAULT_CONFIG`. Runs
once a day via a Windows scheduled task (`AktienbotPaperTrading`, 23:00 daily),
applying the exact same trained-model + weighting + cost-model pipeline as
`benchmark.py` to genuinely new daily closes that autoresearch never saw or
optimized against.

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
- `run_daily.py` is the entry point the scheduled task calls; safe to run more
  than once a day or after a gap (it only processes days it hasn't seen yet).
- `report.py` prints current NAV, cumulative/annualized return, and holdings —
  run it anytime: `"C:\Users\lucap\anaconda3\envs\tf-gpu\python.exe" -m paper_trading.report`

## State (gitignored, regenerated at runtime)

- `state.json` — cash, share holdings (bot + benchmark), last-processed date.
- `nav_log.csv` — one row per trading day: NAV and cumulative return, both books.
- `live_prices.parquet` — accumulated live closes since this system started.
- `run_daily.log` — stdout/stderr from every scheduled run, for troubleshooting.

## Known limitations

- Universe membership uses the latest static snapshot in the S&P 500 CSV —
  real index reconstitutions between refreshes of that file aren't reflected.
- A handful of tickers fail to fetch via yfinance (`BK`, `CTRA`, `HOLX`, `DAY`
  as of this writing — possibly a transient Yahoo issue; `BRK.B`/`BF.B` aren't
  in the historical dataset at all due to dot/dash ticker-symbol mismatches).
  Missing names are simply excluded from that day's picks.
- The Windows scheduled task is "run only when logged on" (no stored
  credentials) — it won't fire if the machine is fully shut down or logged out
  at 23:00, only if it's locked/idle.
- Costs are simulated identically to the backtest (spread_bps + flat fee
  against a compounding capital_eur) — still not real broker execution, slippage,
  or taxes.

## Removing the scheduled task

```
schtasks /Delete /TN "AktienbotPaperTrading" /F
```
