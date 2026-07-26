"""Fetches real, forward-only daily closes for the current S&P 500 universe via
yfinance and appends them to a local parquet, kept separate from the fixed
historical price_df.xlsx (which is never modified).

Only ever appends genuinely new trading days that weren't available when
autoresearch's config was picked -- this is what makes paper_trading a real
out-of-sample forward test instead of another backtest.
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

from quant_bot.data import load_prices, load_universe

LIVE_DIR = Path(__file__).resolve().parent
LIVE_PRICES_PATH = LIVE_DIR / "live_prices.parquet"


def get_current_universe() -> list:
    """Most recent snapshot of real S&P 500 membership -- not live-updated
    itself (the source CSV only refreshes when someone re-exports it), so
    index reconstitutions between refreshes aren't reflected here."""
    df = load_universe(window_years=0, start_year=1900)
    last_row = df.sort_values("date").iloc[-1]
    return last_row["tickers"]


def _download_closes(tickers: list, start: pd.Timestamp) -> pd.DataFrame:
    raw = yf.download(tickers, start=start.strftime("%Y-%m-%d"),
                       progress=False, auto_adjust=True, group_by="ticker")
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw.xs("Close", axis=1, level=1)
    else:
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})
    closes = closes.dropna(how="all")
    return closes


def update_live_prices() -> pd.DataFrame:
    """Fetches any trading days newer than what's already stored (historical
    price_df.xlsx + the running live_prices.parquet) and appends them.
    Returns the full live_prices frame after the update."""
    historical = load_prices()
    universe = get_current_universe()

    if LIVE_PRICES_PATH.exists():
        live = pd.read_parquet(LIVE_PRICES_PATH)
    else:
        live = pd.DataFrame(columns=universe)
        live.index.name = "Date"

    known_max = max(
        historical.index.max(),
        live.index.max() if len(live) else historical.index.min(),
    )
    fetch_start = known_max + pd.Timedelta(days=1)

    new_closes = _download_closes(universe, fetch_start)
    if len(new_closes) == 0:
        return live

    new_closes = new_closes.reindex(columns=universe)
    combined = new_closes if live.empty else pd.concat([live, new_closes], axis=0)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.to_parquet(LIVE_PRICES_PATH)
    return combined


def load_combined_prices() -> pd.DataFrame:
    """Historical price_df.xlsx (untouched, ends 2026-04-10 as of this
    system's build) unioned with whatever paper_trading has fetched since."""
    historical = load_prices()
    if LIVE_PRICES_PATH.exists():
        live = pd.read_parquet(LIVE_PRICES_PATH)
        combined = pd.concat([historical, live.reindex(columns=historical.columns.union(live.columns))], axis=0)
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        return combined
    return historical
