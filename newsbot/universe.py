"""Which companies the bot watches: S&P 500 members (data/sp500_tickers.txt,
taken from the Aktienbot repo's membership snapshot) plus their SEC CIK (to
filter EDGAR filings) and sector (for sector-relative evaluation)."""
import re
from pathlib import Path

from . import net
from .config import ROOT, SECTOR_ETFS, Settings

TICKER_FILE = ROOT / "data" / "sp500_tickers.txt"
SECTOR_FILE = ROOT / "data" / "sectors.csv"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


# symbol changes since the membership snapshot was taken (old -> new)
RENAMED = {"BK": "BNY"}


def norm_ticker(t: str) -> str:
    """Yahoo-style: BRK.B -> BRK-B (SEC uses the same dash form)."""
    t = t.strip().upper().replace(".", "-")
    return RENAMED.get(t, t)


def load_tickers(path: Path = TICKER_FILE) -> list:
    return [norm_ticker(t) for t in path.read_text().split() if t.strip()]


def load_sector_file(path: Path = SECTOR_FILE) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        if "," in line:
            t, s = line.split(",", 1)
            out[t] = s
    return out


def build_sector_file(tickers: list, path: Path = SECTOR_FILE) -> dict:
    """One-time: ask Yahoo for each ticker's sector. ~500 requests, a few
    minutes. The result is committed so normal runs never need it."""
    import yfinance as yf

    sectors = load_sector_file(path)
    for t in tickers:
        if t in sectors:
            continue
        try:
            sectors[t] = yf.Ticker(t).info.get("sector") or ""
        except Exception as e:  # network hiccup, delisted symbol, ...
            print(f"  sector lookup failed for {t}: {e}")
            sectors[t] = ""
    lines = ["ticker,sector"] + [f"{t},{s}" for t, s in sorted(sectors.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sectors


def refresh_universe(con, settings: Settings) -> int:
    """(Re)load the universe table: tickers + CIK + name + sector."""
    if not settings.sec_user_agent:
        raise SystemExit("SEC_USER_AGENT is not set - see .env.example")
    tickers = load_tickers()
    sec = net.get(SEC_TICKERS_URL, headers={"User-Agent": settings.sec_user_agent}).json()
    by_ticker = {norm_ticker(v["ticker"]): v for v in sec.values()}
    sectors = load_sector_file()
    rows = []
    for t in tickers:
        info = by_ticker.get(t)
        rows.append((t, str(info["cik_str"]).zfill(10) if info else None,
                     info["title"] if info else None, sectors.get(t, "")))
    con.execute("DELETE FROM universe")
    con.executemany("INSERT INTO universe (ticker, cik, name, sector) VALUES (?,?,?,?)", rows)
    con.commit()
    missing = [r[0] for r in rows if r[1] is None]
    if missing:
        print(f"  no SEC CIK for {len(missing)} tickers: {', '.join(missing[:15])}")
    return len(rows)


def cik_map(con) -> dict:
    """CIK (10-digit, zero padded) -> ticker."""
    return {r["cik"]: r["ticker"] for r in con.execute("SELECT cik, ticker FROM universe WHERE cik IS NOT NULL")}


def sector_of(con) -> dict:
    return {r["ticker"]: r["sector"] for r in con.execute("SELECT ticker, sector FROM universe")}


def sector_etf(sector: str):
    return SECTOR_ETFS.get(sector)


_SUFFIXES = re.compile(r"\b(inc|corp|corporation|co|company|ltd|plc|holdings?|group|the|n\.?v|s\.?a|/de/|/md/|class [a-c])\b\.?", re.I)


def short_name(name: str) -> str:
    """'APPLE INC.' -> 'apple' -- for matching company names in headlines."""
    s = _SUFFIXES.sub(" ", name.lower())
    s = re.sub(r"[^a-z0-9&\- ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()
