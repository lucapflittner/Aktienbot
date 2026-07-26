"""One-time historical backfill of daily trading volume for every ticker in
price_df.xlsx, over the same date range. Cached separately from prices so the
existing price cache/pipeline is untouched.

Volume wasn't part of the original corpus (only Close was ever downloaded,
see stock_portfoliomanagement_app/app.py's download_all_tickers_close) --
this fills that gap so volume-based features become possible.

Usage: python scripts/backfill_volume.py
"""
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICE_PARQUET = REPO_ROOT / "quant_bot" / "cache" / "prices.parquet"
VOLUME_PARQUET = REPO_ROOT / "quant_bot" / "cache" / "volume.parquet"
CHUNK_SIZE = 50


def main():
    price_df = pd.read_parquet(PRICE_PARQUET)
    price_df["Date"] = pd.to_datetime(price_df["Date"])
    tickers = [c for c in price_df.columns if c != "Date"]
    start = price_df["Date"].min().strftime("%Y-%m-%d")
    end = (price_df["Date"].max() + pd.DateOffset(days=1)).strftime("%Y-%m-%d")

    print(f"Backfilling volume for {len(tickers)} tickers, {start} -> {end}")

    all_data = {}
    failed = []
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        print(f"[{i // CHUNK_SIZE + 1}/{(len(tickers) - 1) // CHUNK_SIZE + 1}] {chunk[0]}..{chunk[-1]}")
        try:
            df = yf.download(chunk, start=start, end=end, group_by="ticker",
                              progress=False, threads=True, auto_adjust=True)
            for ticker in chunk:
                try:
                    if len(chunk) == 1:
                        series = df["Volume"]
                    else:
                        series = df[ticker]["Volume"]
                    all_data[ticker] = series.dropna()
                except Exception:
                    failed.append(ticker)
        except Exception as e:
            print(f"  chunk failed: {e}")
            failed.extend(chunk)
        time.sleep(2)

    volume_df = pd.DataFrame(all_data)
    volume_df.index.name = "Date"
    volume_df = volume_df.sort_index()
    volume_df.to_parquet(VOLUME_PARQUET)

    print(f"\nSaved {volume_df.shape} to {VOLUME_PARQUET}")
    print(f"Failed tickers ({len(failed)}): {failed}")


if __name__ == "__main__":
    main()
