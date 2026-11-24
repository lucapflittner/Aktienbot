"""Optional: any RSS/Atom news feeds (set RSS_FEEDS in .env, comma separated).

Headlines are matched to universe companies by $CASHTAG, "(NASDAQ: XYZ)"-style
mentions or the company's short name. Unmatched headlines are dropped -- macro
coverage comes from GDELT instead.
"""
import hashlib
import re
import time
from datetime import datetime, timezone

from ..db import insert_event
from ..universe import short_name

_EXCHANGE_TAG = re.compile(r"\((?:NYSE|NASDAQ|Nasdaq|NYSE American|AMEX)\s*:\s*([A-Z.\-]{1,6})\)")
_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")


def build_matcher(universe_rows):
    tickers = {r["ticker"] for r in universe_rows}
    names = []
    for r in universe_rows:
        n = short_name(r["name"] or "")
        if len(n) >= 4:  # avoid matching on tiny generic tokens
            names.append((re.compile(rf"\b{re.escape(n)}\b", re.I), r["ticker"]))

    def match(text: str) -> list:
        found = set()
        for rx in (_EXCHANGE_TAG, _CASHTAG):
            found |= {m.replace(".", "-") for m in rx.findall(text) if m.replace(".", "-") in tickers}
        for rx, t in names:
            if rx.search(text):
                found.add(t)
        return sorted(found)

    return match


def ingest(con, settings, now_iso: str) -> dict:
    if not settings.rss_feeds:
        return {"rss": 0}
    import feedparser

    match = build_matcher(con.execute("SELECT ticker, name FROM universe").fetchall())
    added = 0
    for url in settings.rss_feeds:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  rss {url}: {e}")
            continue
        for e in feed.entries:
            title = (e.get("title") or "").strip()
            summary = re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")
            tickers = match(f"{title} {summary}")
            if not title or not tickers:
                continue
            ts = e.get("published_parsed") or e.get("updated_parsed")
            pub = (datetime.fromtimestamp(time.mktime(ts), tz=timezone.utc).isoformat() if ts else now_iso)
            added += insert_event(con, {
                "id": "rss:" + hashlib.sha1((e.get("link") or title).encode()).hexdigest()[:20],
                "source": "rss", "kind": "news", "published_at": pub, "ingested_at": now_iso,
                "tickers": tickers, "title": title, "body": f"{title}\n\n{summary.strip()}"[:4000],
                "url": e.get("link"), "meta": {"feed": url},
            })
    con.commit()
    return {"rss": added}
