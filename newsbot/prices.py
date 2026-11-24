"""Daily closes from Yahoo (yfinance), cached in SQLite, plus the one rule that
keeps every measurement honest: when may a signal be traded?"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 0)


def update_prices(con, tickers: list, lookback_days: int = 10) -> int:
    """Fetch recent closes for `tickers` (re-fetching the last few days so
    late corrections overwrite stale rows). Returns rows written."""
    import yfinance as yf

    tickers = sorted(set(tickers))
    if not tickers:
        return 0
    have = {r["ticker"]: r["d"] for r in con.execute(
        "SELECT ticker, MAX(date) d FROM prices GROUP BY ticker")}
    oldest = min((have.get(t) or "2000-01-01") for t in tickers)
    start = max(pd.Timestamp(oldest) - pd.Timedelta(days=lookback_days),
                pd.Timestamp.today().normalize() - pd.Timedelta(days=400))
    raw = yf.download(tickers, start=start.strftime("%Y-%m-%d"), progress=False,
                      auto_adjust=True, group_by="ticker", threads=True)
    if raw is None or raw.empty:
        return 0
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw.xs("Close", axis=1, level=1)
    else:
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})
    rows = [(t, d.strftime("%Y-%m-%d"), float(v))
            for t in closes.columns for d, v in closes[t].dropna().items()]
    # drop today's bar while the market is still open - it's not a close yet
    now_ny = datetime.now(NY)
    if now_ny.time() < MARKET_CLOSE:
        today = now_ny.strftime("%Y-%m-%d")
        rows = [r for r in rows if r[1] != today]
    con.executemany("INSERT OR REPLACE INTO prices (ticker, date, close) VALUES (?,?,?)", rows)
    con.commit()
    return len(rows)


def close_matrix(con, tickers=None) -> pd.DataFrame:
    q = "SELECT ticker, date, close FROM prices"
    df = pd.read_sql_query(q, con)
    if tickers is not None:
        df = df[df["ticker"].isin(list(tickers))]
    if df.empty:
        return pd.DataFrame()
    m = df.pivot(index="date", columns="ticker", values="close").sort_index()
    m.index = pd.to_datetime(m.index)
    return m


def close_timestamp(day) -> datetime:
    """16:00 New York on `day`, as an aware datetime."""
    d = pd.Timestamp(day).date()
    return datetime.combine(d, MARKET_CLOSE, tzinfo=NY)


def first_tradable_close(available_at: datetime, trading_days) -> pd.Timestamp:
    """The first daily close at or after the moment a signal became usable.
    A filing at 15:59 with 30 min reaction time misses that day's close and
    fills on the next one. Returns None if that close hasn't happened yet."""
    for d in trading_days:
        if close_timestamp(d) >= available_at:
            return pd.Timestamp(d)
    return None


def signal_available_at(published_iso: str, reaction_minutes: int) -> datetime:
    return datetime.fromisoformat(published_iso) + timedelta(minutes=reaction_minutes)
