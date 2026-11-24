"""The honest scoreboard: did the scores predict anything?

Event study over every non-neutral score: enter at the first close after the
news became usable, measure the return over 1/3/5/10 trading days RELATIVE to
the sector ETF (stocks) or SPY (sector ETFs), signed by the predicted
direction. A real signal shows a positive mean with |t| > 2 and a hit rate
above 50% -- per source, so a useless source can be switched off.
"""
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .prices import first_tradable_close
from .universe import sector_etf, sector_of

HORIZONS = (1, 3, 5, 10)


def event_returns(con, settings, closes: pd.DataFrame) -> pd.DataFrame:
    rows = con.execute(
        "SELECT s.*, e.published_at, e.source FROM scores s JOIN events e ON e.id = s.event_id "
        "WHERE s.direction != 0").fetchall()
    if closes.empty or settings.benchmark not in closes:
        return pd.DataFrame()
    days = list(closes[settings.benchmark].dropna().index)
    sectors = sector_of(con)
    react = timedelta(minutes=settings.reaction_minutes)
    out = []
    for r in rows:
        avail = datetime.fromisoformat(r["published_at"]) + react
        d0 = first_tradable_close(avail, days)
        if d0 is None or r["target"] not in closes:
            continue
        ref = sector_etf(sectors.get(r["target"], "")) or settings.benchmark
        if r["target"] == ref or ref not in closes:
            ref = settings.benchmark
        i0 = days.index(d0)
        rec = {"event_id": r["event_id"], "target": r["target"], "source": r["source"],
               "scorer": r["scorer"], "direction": r["direction"], "confidence": r["confidence"],
               "strength": r["strength"], "entry": d0}
        for h in HORIZONS:
            if i0 + h >= len(days):
                rec[f"ex_{h}d"] = np.nan
                continue
            d1 = days[i0 + h]
            a = closes.at[d1, r["target"]] / closes.at[d0, r["target"]] - 1
            b = closes.at[d1, ref] / closes.at[d0, ref] - 1
            rec[f"ex_{h}d"] = r["direction"] * (a - b)  # signed excess return
        out.append(rec)
    return pd.DataFrame(out)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    rows = []
    for (source, scorer), g in df.groupby(["source", "scorer"]):
        for h in HORIZONS:
            x = g[f"ex_{h}d"].dropna()
            if len(x) == 0:
                continue
            t = x.mean() / x.std(ddof=1) * np.sqrt(len(x)) if len(x) > 2 and x.std() > 0 else np.nan
            rows.append({"source": source, "scorer": scorer, "horizon": f"{h}d", "n": len(x),
                         "mean_signed_excess_%": round(100 * x.mean(), 3),
                         "hit_rate": round((x > 0).mean(), 3), "t_stat": round(t, 2)})
    return pd.DataFrame(rows)


def by_confidence(df: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:
    """Calibration: higher stated confidence should mean better outcomes."""
    col = f"ex_{horizon}d"
    if df.empty or df[col].notna().sum() == 0:
        return pd.DataFrame()
    d = df.dropna(subset=[col]).copy()
    d["bucket"] = pd.cut(d["confidence"], [0, 0.5, 0.65, 0.8, 1.0], include_lowest=True)
    return d.groupby("bucket", observed=True)[col].agg(
        n="count", mean=lambda s: round(100 * s.mean(), 3), hit=lambda s: round((s > 0).mean(), 3))


def scored_targets(con) -> list:
    return [r["target"] for r in con.execute("SELECT DISTINCT target FROM scores WHERE direction != 0")]
