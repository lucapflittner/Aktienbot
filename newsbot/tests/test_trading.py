from datetime import datetime, timezone

import pandas as pd

from newsbot import broker, db, evaluate, prices
from newsbot.signals import compute_signals


def _scored(con, eid, target, published, direction=1, strength=1.0, conf=0.9):
    db.insert_event(con, {"id": eid, "source": "edgar_8k", "kind": "filing", "published_at": published,
                          "ingested_at": "x", "tickers": [target], "title": eid, "meta": {}})
    con.execute("INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?)",
                (eid, target, direction, strength, conf, 5, 1.0, "r", "llm:fake", "now"))
    con.commit()


def test_fill_is_first_close_after_news():
    days = list(pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24"]))
    # 15:45 NY + 30 min reaction misses that day's 16:00 close
    late = prices.signal_available_at("2026-11-23T20:45:00+00:00", 30)
    assert prices.first_tradable_close(late, days) == pd.Timestamp("2026-11-24")
    early = prices.signal_available_at("2026-11-23T14:00:00+00:00", 30)
    assert prices.first_tradable_close(early, days) == pd.Timestamp("2026-11-23")
    # weekend filing -> Monday
    sat = prices.signal_available_at("2026-11-21T12:00:00+00:00", 30)
    assert prices.first_tradable_close(sat, days) == pd.Timestamp("2026-11-23")
    assert prices.first_tradable_close(late, days[:2]) is None


def test_signals_ignore_future_news(con, settings):
    _scored(con, "past", "AAA", "2026-11-23T14:00:00+00:00")
    _scored(con, "future", "BBB", "2026-11-23T20:50:00+00:00")  # after the close
    sig = compute_signals(con, settings, prices.close_timestamp("2026-11-23"))
    assert "AAA" in sig and "BBB" not in sig


def test_signal_decays(con, settings):
    _scored(con, "e", "AAA", "2026-11-20T14:00:00+00:00")
    t0 = compute_signals(con, settings, datetime(2026, 11, 20, 15, tzinfo=timezone.utc))["AAA"]
    t1 = compute_signals(con, settings, datetime(2026, 11, 23, 15, tzinfo=timezone.utc))["AAA"]
    assert 0 < t1 < t0


def _closes():
    idx = pd.to_datetime(["2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26",
                          "2026-11-27", "2026-11-30", "2026-12-01"])
    return pd.DataFrame({"SPY": [100, 101, 102, 103, 104, 105, 106, 107],
                         "AAA": [50, 50, 55, 56, 57, 58, 59, 60.0],
                         "XLK": [10] * 8}, index=idx)


def test_broker_buys_after_news_and_exits_after_hold(con, settings):
    settings.hold_days = 3
    closes = _closes()
    from newsbot.db import kv_set
    kv_set(con, "last_processed_day", "2026-11-20")
    _scored(con, "e", "AAA", "2026-11-23T14:00:00+00:00")
    res = broker.run(con, settings, closes)
    trades = con.execute("SELECT date, ticker, side, price FROM trades ORDER BY id").fetchall()
    assert (trades[0]["date"], trades[0]["side"], trades[0]["price"]) == ("2026-11-23", "BUY", 50)
    assert any(t["side"] == "SELL" for t in trades)
    sell = [t for t in trades if t["side"] == "SELL"][0]
    assert sell["date"] in ("2026-11-26", "2026-11-27")  # within the hold window, not later
    nav = res[-1]["nav"]
    assert nav > settings.capital  # AAA rose 50 -> 57+, costs are small
    assert res[-1]["bench_nav"] == settings.capital * 107 / 101


def test_event_study_signed_excess(con, settings):
    _scored(con, "e", "AAA", "2026-11-23T14:00:00+00:00")
    con.execute("INSERT INTO universe VALUES ('AAA', '1', 'A', 'Technology')")
    df = evaluate.event_returns(con, settings, _closes())
    r = df.iloc[0]
    assert r["entry"] == pd.Timestamp("2026-11-23")
    assert abs(r["ex_1d"] - 0.10) < 1e-9  # AAA +10%, XLK flat -> sector-relative
    summ = evaluate.summarize(df)
    assert set(summ["horizon"]) >= {"1d", "3d"}
