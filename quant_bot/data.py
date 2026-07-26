"""Loads the real S&P 500 price history and historical index-membership corpus.

Both source files are already present in the repo (yfinance downloads and
fja05680/sp500 membership export) — no re-scraping needed. The xlsx read is
slow (~35s for 884 tickers), so a parquet cache sits next to it and is reused
whenever the source file hasn't changed.
"""
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICE_XLSX = REPO_ROOT / "stock_portfoliomanagement_app" / "price_df.xlsx"
PRICE_PARQUET = Path(__file__).resolve().parent / "cache" / "prices.parquet"
VOLUME_PARQUET = Path(__file__).resolve().parent / "cache" / "volume.parquet"
SP500_CSV = REPO_ROOT / "S&P 500 Historical Components & Changes.csv"


def load_prices() -> pd.DataFrame:
    """Close prices, Date-indexed, one column per ticker."""
    if PRICE_PARQUET.exists() and PRICE_PARQUET.stat().st_mtime >= PRICE_XLSX.stat().st_mtime:
        df = pd.read_parquet(PRICE_PARQUET)
    else:
        df = pd.read_excel(PRICE_XLSX)
        PRICE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(PRICE_PARQUET)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date").sort_index()


def load_volume() -> pd.DataFrame:
    """Daily trading volume, Date-indexed, one column per ticker. Backfilled
    separately via scripts/backfill_volume.py (the original corpus only ever
    fetched Close) -- regenerate that script's output if this file is missing,
    there is no xlsx source to fall back to."""
    df = pd.read_parquet(VOLUME_PARQUET)
    return df.sort_index()


def load_universe(window_years: int, start_year: int) -> pd.DataFrame:
    """Historical S&P 500 membership per fja05680/sp500 (real corpus, not synthetic)."""
    df = pd.read_csv(SP500_CSV)
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df = df[df["year"] >= start_year - window_years].copy()
    df["tickers"] = df["tickers"].apply(lambda x: x.split(","))
    return df.sort_values("date")
