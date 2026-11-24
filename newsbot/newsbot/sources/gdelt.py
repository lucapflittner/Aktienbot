"""World news via the GDELT DOC 2.0 API (free, global, updated every 15 min).

Per macro theme, collects the headlines that are new since the last run into
one digest event. The LLM then judges which SECTORS that digest moves --
world news rarely says anything about one specific stock, but tariffs, oil
shocks, rate surprises or wars hit whole industries.

GDELT returns headlines and links only, no article text -- article sites are
not scraped (terms of use, paywalls).
"""
import hashlib
from datetime import datetime, timezone

from .. import net
from ..db import insert_event, kv_get, kv_set

API = "https://api.gdeltproject.org/api/v2/doc/doc"

THEMES = {
    "trade_tariffs": '(tariff OR tariffs OR "trade war" OR "export controls" OR sanctions)',
    "monetary_policy": '("Federal Reserve" OR "interest rates" OR "rate cut" OR "rate hike" OR inflation OR ECB)',
    "energy_oil": '(OPEC OR "oil price" OR "crude oil" OR "natural gas price" OR "oil supply")',
    "geopolitics": '(war OR invasion OR missile OR ceasefire OR "military strike" OR blockade)',
    "tech_ai_chips": '(semiconductor OR chipmaker OR "AI chips" OR "data center" OR "artificial intelligence regulation")',
    "health_regulation": '(FDA OR "drug pricing" OR Medicare OR pandemic OR outbreak)',
    "banking_credit": '("bank failure" OR "credit crunch" OR "bond yields" OR "debt ceiling" OR downgrade)',
    "supply_chain": '("supply chain" OR shortage OR "port strike" OR "shipping rates" OR "Suez" OR "Panama Canal")',
}


# Restrict to established news outlets: GDELT's open web crawl is noisy
# (local TV sites, aggregators). Set GDELT_ALL_DOMAINS=1 to search everything.
DOMAINS = ("reuters.com", "apnews.com", "cnbc.com", "bloomberg.com", "wsj.com", "ft.com",
           "marketwatch.com", "barrons.com", "nytimes.com", "washingtonpost.com",
           "bbc.co.uk", "theguardian.com", "economist.com", "axios.com", "politico.com",
           "aljazeera.com", "dw.com", "finance.yahoo.com", "fortune.com", "businessinsider.com")


def _domain_filter() -> str:
    import os
    if os.environ.get("GDELT_ALL_DOMAINS") == "1":
        return ""
    return " (" + " OR ".join(f"domainis:{d}" for d in DOMAINS) + ")"


def _parse_seendate(s: str) -> str:
    return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()


def fetch_theme(query: str, timespan: str, max_records: int) -> list:
    resp = net.get(API, params={
        "query": f"{query}{_domain_filter()} sourcelang:english", "mode": "artlist", "format": "json",
        "maxrecords": max_records, "timespan": timespan, "sort": "datedesc"}, timeout=60, retries=1)
    try:
        data = resp.json()
    except ValueError:  # GDELT answers plain text on malformed/too-short queries
        print(f"  gdelt: non-JSON reply: {resp.text[:160]!r}")
        return []
    return data.get("articles", []) or []


def build_digest(theme: str, articles: list, seen_urls: set) -> dict:
    fresh = [a for a in articles if a.get("url") not in seen_urls and a.get("title")]
    if not fresh:
        return None
    # collapse syndicated copies of the same headline
    uniq = {}
    for a in fresh:
        uniq.setdefault(a["title"].strip().lower(), a)
    fresh = sorted(uniq.values(), key=lambda a: a.get("seendate", ""), reverse=True)
    lines = [f"- [{a.get('domain', '?')}, {a.get('seendate', '')}] {a['title'].strip()}" for a in fresh]
    newest = _parse_seendate(fresh[0]["seendate"]) if fresh[0].get("seendate") else None
    key = hashlib.sha1("".join(sorted(a["url"] for a in fresh)).encode()).hexdigest()[:16]
    return {
        "id": f"gdelt:{theme}:{key}", "source": "gdelt", "kind": "macro",
        "published_at": newest, "tickers": [],
        "title": f"World news digest - {theme} ({len(fresh)} new headlines)",
        "body": "\n".join(lines), "url": None,
        "meta": {"theme": theme, "urls": [a["url"] for a in fresh]},
    }


def ingest(con, settings, now_iso: str) -> dict:
    if not settings.gdelt_enabled:
        return {"gdelt": 0}
    seen = set(kv_get(con, "gdelt_seen_urls", []))
    added, new_urls, failures = 0, [], 0
    for theme, query in THEMES.items():
        try:
            arts = fetch_theme(query, "6h", settings.gdelt_max_records)
            failures = 0
        except Exception as e:
            print(f"  gdelt {theme}: {e}")
            failures += 1
            if failures >= 2:  # throttled / down - don't burn minutes on backoff
                print("  gdelt unavailable, skipping the remaining themes this run")
                break
            continue
        ev = build_digest(theme, arts, seen)
        if ev is None:
            continue
        ev["ingested_at"] = now_iso
        ev["published_at"] = ev["published_at"] or now_iso
        added += insert_event(con, ev)
        new_urls += ev["meta"]["urls"]
    kv_set(con, "gdelt_seen_urls", (list(seen) + new_urls)[-5000:])
    con.commit()
    return {"gdelt": added}
