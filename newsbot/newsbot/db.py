"""SQLite storage. One file, no server -- the whole bot's state lives here.

Timestamps are stored as UTC ISO-8601 strings ("2026-11-23T14:15:00+00:00").
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,      -- source-specific stable id (accession no., url hash)
    source        TEXT NOT NULL,         -- edgar_form4 | edgar_8k | gdelt | rss
    kind          TEXT NOT NULL,         -- insider | filing | macro | news
    published_at  TEXT NOT NULL,         -- when the information became public (UTC)
    ingested_at   TEXT NOT NULL,
    tickers       TEXT NOT NULL,         -- JSON list, may be empty for macro
    title         TEXT NOT NULL,
    body          TEXT,                  -- text handed to the LLM (truncated)
    url           TEXT,
    meta          TEXT                   -- JSON, source-specific structured fields
);
CREATE INDEX IF NOT EXISTS ix_events_pub ON events(published_at);

CREATE TABLE IF NOT EXISTS scores (
    event_id      TEXT NOT NULL REFERENCES events(id),
    target        TEXT NOT NULL,         -- ticker or sector ETF
    direction     INTEGER NOT NULL,      -- -1 | 0 | 1
    strength      REAL NOT NULL,         -- 0..1 expected size of the move
    confidence    REAL NOT NULL,         -- 0..1
    horizon_days  INTEGER NOT NULL,
    novelty       REAL NOT NULL,         -- 0..1, 0 = already widely known
    rationale     TEXT,
    scorer        TEXT NOT NULL,         -- rule:insider | llm:<model>
    scored_at     TEXT NOT NULL,
    PRIMARY KEY (event_id, target, scorer)
);
CREATE TABLE IF NOT EXISTS score_attempts (
    event_id      TEXT PRIMARY KEY,
    attempted_at  TEXT NOT NULL,
    status        TEXT NOT NULL,         -- ok | error | skipped
    detail        TEXT
);

CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL, date TEXT NOT NULL, close REAL NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS universe (
    ticker TEXT PRIMARY KEY, cik TEXT, name TEXT, sector TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY, shares REAL NOT NULL, entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL, signal REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, ticker TEXT NOT NULL,
    side TEXT NOT NULL, shares REAL NOT NULL, price REAL NOT NULL, cost REAL NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS nav (
    date TEXT PRIMARY KEY, cash REAL NOT NULL, nav REAL NOT NULL, bench_nav REAL NOT NULL,
    n_positions INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


@contextmanager
def tx(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def insert_event(con, ev: dict) -> bool:
    """Insert if new. Returns True when the event was not seen before."""
    cur = con.execute(
        "INSERT OR IGNORE INTO events (id, source, kind, published_at, ingested_at, tickers, "
        "title, body, url, meta) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ev["id"], ev["source"], ev["kind"], ev["published_at"], ev["ingested_at"],
         json.dumps(ev.get("tickers", [])), ev["title"], ev.get("body"), ev.get("url"),
         json.dumps(ev.get("meta", {}))),
    )
    return cur.rowcount == 1


def kv_get(con, key, default=None):
    row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value)))
