"""Aggregate scores into one number per ticker / sector ETF at a point in time.

signal = sum over scores of  direction * strength * confidence * novelty_w * decay
  decay     = 0.5 ** (age_hours / halflife)  -- news fades
  novelty_w = 0.5 + 0.5 * novelty            -- old news counts half

Only scores whose event was public (plus reaction time) BEFORE `as_of` are
used, so replaying past days can never peek at later news.
"""
from datetime import datetime, timedelta

import pandas as pd


def compute_signals(con, settings, as_of: datetime) -> pd.Series:
    rows = con.execute(
        "SELECT s.target, s.direction, s.strength, s.confidence, s.novelty, s.horizon_days, "
        "e.published_at FROM scores s JOIN events e ON e.id = s.event_id "
        "WHERE s.direction != 0 AND s.confidence >= ?", (settings.min_confidence,)).fetchall()
    react = timedelta(minutes=settings.reaction_minutes)
    acc: dict = {}
    for r in rows:
        avail = datetime.fromisoformat(r["published_at"]) + react
        if avail > as_of:
            continue
        age_h = (as_of - avail).total_seconds() / 3600
        if age_h > r["horizon_days"] * 24 * 7 / 5:  # horizon in trading days -> calendar
            continue
        decay = 0.5 ** (age_h / settings.signal_halflife_hours)
        v = r["direction"] * r["strength"] * r["confidence"] * (0.5 + 0.5 * r["novelty"]) * decay
        acc[r["target"]] = acc.get(r["target"], 0.0) + v
    return pd.Series(acc, dtype=float).sort_values(ascending=False)
