"""Turn raw events into scores: direction, strength, confidence per ticker/sector.

- Insider trades are scored by fixed rules (no LLM): the research on Form 4
  is clear enough that a rule beats a language model's guess.
- 8-K filings and RSS news go to the local LLM, one call per event.
- World-news digests go to the LLM with a sector question.
"""
import json
import math
from datetime import datetime, timezone

from .config import SECTOR_ETFS
from .llm import LLMError

COMPANY_SYSTEM = """You are a sell-side equity analyst. You read one corporate disclosure or news item about a single US large-cap company and judge how it should move that company's stock RELATIVE TO ITS SECTOR over the next trading days.

Rules:
- Judge only from the text. If it is routine, boilerplate or already expected (scheduled dividend, routine board change, exhibits only), answer direction 0.
- Earnings: compare reported numbers and guidance to what the text says about expectations/prior guidance; a beat with lowered guidance is not clearly positive.
- Be calibrated: most disclosures are neutral. Use confidence above 0.7 only for unambiguous, material news.
- You do NOT know today's stock price or how the market already reacted; do not invent it.

Reply with ONE JSON object and nothing else:
{"direction": -1 | 0 | 1, "strength": 0.0-1.0, "confidence": 0.0-1.0, "horizon_days": 1-20, "novelty": 0.0-1.0, "rationale": "<max 2 sentences>"}
strength: 0.2 ~ a 1% relative move, 0.5 ~ 3%, 1.0 ~ 10% or more. novelty: 1 = genuinely new information, 0 = already known/expected."""

MACRO_SYSTEM = """You are a macro strategist. You receive a digest of world-news headlines from the last hours on one theme. Decide whether they contain NEW information that should move specific US equity SECTORS relative to the overall market over the next days.

Allowed sectors (use these exact names): {sectors}

Rules:
- Headlines repeating known, ongoing stories are not new -> return an empty list.
- Name at most 3 sectors, only where the causal link is direct (e.g. oil supply shock -> Energy up, airlines in Industrials down).
- Be calibrated: most digests produce an empty list.

Reply with ONE JSON object and nothing else:
{{"impacts": [{{"sector": "<name>", "direction": -1 | 1, "strength": 0.0-1.0, "confidence": 0.0-1.0, "horizon_days": 1-20, "rationale": "<1 sentence>"}}]}}"""


def _clamp(x, lo, hi, default):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(x) else min(hi, max(lo, x))


def normalize_company(raw: dict) -> dict:
    d = int(_clamp(raw.get("direction"), -1, 1, 0))
    return {
        "direction": d,
        "strength": _clamp(raw.get("strength"), 0, 1, 0.0),
        "confidence": _clamp(raw.get("confidence"), 0, 1, 0.0),
        "horizon_days": int(_clamp(raw.get("horizon_days"), 1, 20, 5)),
        "novelty": _clamp(raw.get("novelty"), 0, 1, 0.5),
        "rationale": str(raw.get("rationale", ""))[:500],
    }


def normalize_macro(raw: dict) -> list:
    out = []
    for imp in (raw.get("impacts") or [])[:3]:
        etf = SECTOR_ETFS.get(str(imp.get("sector", "")).strip())
        if not etf:
            continue
        s = normalize_company(imp)
        if s["direction"] != 0:
            out.append((etf, s))
    return out


def score_insider(meta: dict, min_value: float) -> dict:
    """Open-market purchases by officers/directors are among the best-documented
    insider signals; sales are mostly diversification/taxes and carry little
    information. Pre-planned 10b5-1 trades are discounted."""
    buys = sum(t["value"] for t in meta["trades"] if t["code"] == "P")
    sells = sum(t["value"] for t in meta["trades"] if t["code"] == "S")
    owner = meta["owner"]
    title = (owner.get("title") or "").lower()
    top_exec = any(k in title for k in ("chief executive", "ceo", "chief financial", "cfo", "president", "chair"))
    insider = owner.get("is_officer") or owner.get("is_director")
    base = {"horizon_days": 20, "novelty": 1.0}

    if buys >= min_value and buys >= sells:
        strength = min(1.0, 0.25 + 0.15 * math.log10(buys / min_value + 1) * 3)
        conf = 0.55 + (0.15 if top_exec else 0) + (0.05 if insider else -0.1)
        if meta.get("planned_10b5_1"):
            conf -= 0.25
        return {**base, "direction": 1, "strength": round(strength, 3), "confidence": round(min(conf, 0.85), 3),
                "rationale": f"open-market purchase ${buys:,.0f} by {owner.get('name')} ({owner.get('title') or 'insider'})"}
    if sells >= 10 * min_value and top_exec and not meta.get("planned_10b5_1"):
        return {**base, "direction": -1, "strength": 0.2, "confidence": 0.3,
                "rationale": f"unplanned sale ${sells:,.0f} by top executive"}
    return {**base, "direction": 0, "strength": 0.0, "confidence": 0.0,
            "rationale": f"not informative (buys ${buys:,.0f}, sells ${sells:,.0f})"}


def _save(con, event_id, target, s, scorer, now_iso):
    con.execute(
        "INSERT OR REPLACE INTO scores (event_id, target, direction, strength, confidence, "
        "horizon_days, novelty, rationale, scorer, scored_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (event_id, target, s["direction"], s["strength"], s["confidence"], s["horizon_days"],
         s["novelty"], s["rationale"], scorer, now_iso))


def _attempt(con, event_id, status, detail, now_iso):
    con.execute("INSERT OR REPLACE INTO score_attempts (event_id, attempted_at, status, detail) "
                "VALUES (?,?,?,?)", (event_id, now_iso, status, (detail or "")[:500]))


def score_pending(con, settings, llm, now_iso: str, limit: int = 200) -> dict:
    """Score every event that has no successful attempt yet. LLM failures are
    recorded and retried next run, so a sleeping LLM server loses nothing."""
    rows = con.execute(
        "SELECT e.* FROM events e LEFT JOIN score_attempts a ON a.event_id = e.id "
        "WHERE a.event_id IS NULL OR a.status = 'error' ORDER BY e.published_at LIMIT ?",
        (limit,)).fetchall()
    stats = {"rule": 0, "llm": 0, "errors": 0}
    llm_down = False
    for ev in rows:
        tickers = json.loads(ev["tickers"])
        meta = json.loads(ev["meta"] or "{}")
        try:
            if ev["kind"] == "insider":
                _save(con, ev["id"], tickers[0], score_insider(meta, settings.insider_min_value_usd),
                      "rule:insider", now_iso)
                stats["rule"] += 1
            elif llm_down:
                continue
            elif ev["kind"] == "macro":
                system = MACRO_SYSTEM.format(sectors=", ".join(SECTOR_ETFS))
                impacts = normalize_macro(llm.chat_json(system, ev["body"] or ev["title"]))
                for etf, s in impacts:
                    _save(con, ev["id"], etf, s, f"llm:{llm.name}", now_iso)
                stats["llm"] += 1
            else:
                user = f"Company ticker(s): {', '.join(tickers)}\nTitle: {ev['title']}\n\n{ev['body'] or ''}"
                s = normalize_company(llm.chat_json(COMPANY_SYSTEM, user[: settings.llm_max_input_chars]))
                for t in tickers[:3]:
                    _save(con, ev["id"], t, s, f"llm:{llm.name}", now_iso)
                stats["llm"] += 1
            _attempt(con, ev["id"], "ok", None, now_iso)
        except (LLMError, OSError, ValueError, KeyError) as e:
            stats["errors"] += 1
            _attempt(con, ev["id"], "error", str(e), now_iso)
            if "Connection" in type(e).__name__ or "refused" in str(e).lower():
                llm_down = True  # don't hammer a server that isn't running
                print("  LLM server not reachable - scoring the rest next run")
        con.commit()
    return stats


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
