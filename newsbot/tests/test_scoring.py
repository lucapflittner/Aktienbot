import json

import pytest

from newsbot import db, scoring
from newsbot.llm import LLMError, extract_json


@pytest.mark.parametrize("reply", [
    '{"direction": 1, "strength": 0.4}',
    '<think>hmm {not json}</think>\n{"direction": 1, "strength": 0.4}',
    'Sure!\n```json\n{"direction": 1, "strength": 0.4}\n```',
    'reasoning without open tag </think> {"direction": 1, "strength": 0.4, "rationale": "a } b"}',
])
def test_extract_json_variants(reply):
    d = extract_json(reply)
    assert d["direction"] == 1 and d["strength"] == 0.4


def test_extract_json_fails_loudly():
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_normalize_clamps_garbage():
    s = scoring.normalize_company({"direction": 5, "strength": "high", "confidence": 2, "horizon_days": 0})
    assert s["direction"] == 1 and s["strength"] == 0.0 and s["confidence"] == 1.0 and s["horizon_days"] == 1


def test_normalize_macro_maps_sectors_and_drops_unknown():
    out = scoring.normalize_macro({"impacts": [
        {"sector": "Energy", "direction": 1, "strength": 0.5, "confidence": 0.7},
        {"sector": "Crypto", "direction": 1, "strength": 0.5, "confidence": 0.7},
        {"sector": "Utilities", "direction": 0}]})
    assert [etf for etf, _ in out] == ["XLE"]


def _meta(code, value, title="Chief Executive Officer", planned=False):
    return {"owner": {"name": "X", "is_officer": True, "is_director": False, "title": title},
            "planned_10b5_1": planned,
            "trades": [{"code": code, "value": value, "shares": 1, "price": value}]}


def test_insider_rules():
    buy = scoring.score_insider(_meta("P", 1_000_000), 100_000)
    assert buy["direction"] == 1 and buy["confidence"] >= 0.7
    planned = scoring.score_insider(_meta("P", 1_000_000, planned=True), 100_000)
    assert planned["confidence"] < buy["confidence"]
    small = scoring.score_insider(_meta("P", 10_000), 100_000)
    assert small["direction"] == 0
    routine_sale = scoring.score_insider(_meta("S", 500_000), 100_000)
    assert routine_sale["direction"] == 0


class FakeLLM:
    name = "fake"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, 0

    def chat_json(self, system, user, max_tokens=800):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


def _event(con, eid, kind, tickers, body="text"):
    db.insert_event(con, {"id": eid, "source": "edgar_8k" if kind == "filing" else "gdelt", "kind": kind,
                          "published_at": "2026-11-23T15:00:00+00:00", "ingested_at": "x",
                          "tickers": tickers, "title": eid, "body": body, "meta": {}})


def test_score_pending_and_retry_after_llm_error(con, settings):
    _event(con, "a", "filing", ["AAPL"])
    down = FakeLLM(error=ConnectionError("Connection refused"))
    st = scoring.score_pending(con, settings, down, "now")
    assert st["errors"] == 1 and con.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0

    up = FakeLLM(reply={"direction": 1, "strength": 0.5, "confidence": 0.8, "horizon_days": 3,
                        "novelty": 1, "rationale": "beat"})
    scoring.score_pending(con, settings, up, "now")
    row = con.execute("SELECT * FROM scores").fetchone()
    assert row["target"] == "AAPL" and row["direction"] == 1 and row["scorer"] == "llm:fake"
    # already scored -> not sent again
    scoring.score_pending(con, settings, up, "now")
    assert up.calls == 1


def test_macro_event_scores_sector_etfs(con, settings):
    _event(con, "m", "macro", [])
    llm = FakeLLM(reply={"impacts": [{"sector": "Energy", "direction": 1, "strength": 0.6,
                                      "confidence": 0.7, "horizon_days": 5, "rationale": "oil"}]})
    scoring.score_pending(con, settings, llm, "now")
    assert con.execute("SELECT target FROM scores").fetchone()[0] == "XLE"
