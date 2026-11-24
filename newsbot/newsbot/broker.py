"""Paper broker: long-only, event-driven, daily closes.

Each processed trading day D:
  1. signals as of D's 16:00 close (only news public before that)
  2. sell positions held >= hold_days or whose signal fell below exit_threshold
  3. buy the strongest new signals >= entry_threshold, equal slices of NAV,
     up to max_positions
  4. mark to market, also a buy-and-hold benchmark (SPY)
Fills are at D's close -- never at a price from before the news was public.
Costs: spread_bps per side on traded value + flat fee per order (same model
as the Aktienbot paper trader).
"""
import pandas as pd

from .db import kv_get, kv_set
from .prices import close_timestamp
from .signals import compute_signals


def _cost(value: float, settings) -> float:
    return abs(value) * settings.spread_bps / 1e4 + settings.flat_fee


def step_day(con, settings, day: pd.Timestamp, px: pd.Series, trading_days: list) -> dict:
    """Process one trading day. `px` = that day's closes (ticker -> price)."""
    cash = kv_get(con, "cash", settings.capital)
    positions = {r["ticker"]: dict(r) for r in con.execute("SELECT * FROM positions")}
    sig = compute_signals(con, settings, close_timestamp(day))
    dstr = day.strftime("%Y-%m-%d")
    actions = []

    def held_days(entry_date):
        return sum(1 for d in trading_days if pd.Timestamp(entry_date) < d <= day)

    # --- exits ---
    for t, p in list(positions.items()):
        price = px.get(t)
        if price is None or pd.isna(price):
            continue  # no quote today (halt, data gap) - try again tomorrow
        s = float(sig.get(t, 0.0))
        reason = ("hold period over" if held_days(p["entry_date"]) >= settings.hold_days
                  else "signal faded" if s < settings.exit_threshold else None)
        if reason:
            value = p["shares"] * price
            cost = _cost(value, settings)
            cash += value - cost
            con.execute("DELETE FROM positions WHERE ticker=?", (t,))
            con.execute("INSERT INTO trades (date, ticker, side, shares, price, cost, reason) "
                        "VALUES (?,?,?,?,?,?,?)", (dstr, t, "SELL", p["shares"], price, cost, reason))
            positions.pop(t)
            actions.append(f"SELL {t} @ {price:.2f} ({reason})")

    # --- entries ---
    nav_now = cash + sum(p["shares"] * px.get(t, p["entry_price"]) for t, p in positions.items())
    slots = settings.max_positions - len(positions)
    candidates = [(t, v) for t, v in sig.items()
                  if v >= settings.entry_threshold and t not in positions
                  and t in px and not pd.isna(px[t])]
    for t, v in candidates[:max(slots, 0)]:
        budget = min(nav_now / settings.max_positions, cash)
        if budget <= settings.flat_fee * 20:
            break
        cost = _cost(budget, settings)
        shares = (budget - cost) / px[t]
        cash -= budget
        con.execute("INSERT INTO positions (ticker, shares, entry_date, entry_price, signal) "
                    "VALUES (?,?,?,?,?)", (t, shares, dstr, float(px[t]), float(v)))
        con.execute("INSERT INTO trades (date, ticker, side, shares, price, cost, reason) "
                    "VALUES (?,?,?,?,?,?,?)", (dstr, t, "BUY", shares, float(px[t]), cost, f"signal {v:.2f}"))
        positions[t] = {"shares": shares, "entry_price": float(px[t])}
        actions.append(f"BUY {t} @ {px[t]:.2f} (signal {v:.2f})")

    # --- mark to market + benchmark ---
    nav = cash + sum(p["shares"] * float(px.get(t, p["entry_price"])) for t, p in positions.items())
    bench_units = kv_get(con, "bench_units")
    b = px.get(settings.benchmark)
    if bench_units is None and b is not None and not pd.isna(b):
        bench_units = settings.capital / float(b)
        kv_set(con, "bench_units", bench_units)
    bench_nav = bench_units * float(b) if bench_units and b is not None and not pd.isna(b) else settings.capital
    con.execute("INSERT OR REPLACE INTO nav (date, cash, nav, bench_nav, n_positions) VALUES (?,?,?,?,?)",
                (dstr, cash, nav, bench_nav, len(positions)))
    kv_set(con, "cash", cash)
    kv_set(con, "last_processed_day", dstr)
    con.commit()
    return {"date": dstr, "nav": nav, "bench_nav": bench_nav, "actions": actions}


def run(con, settings, closes: pd.DataFrame) -> list:
    """Process every trading day after the last processed one. On the very
    first run, start with the most recent close (no backfilled history)."""
    if closes.empty or settings.benchmark not in closes.columns:
        return []
    trading_days = list(closes[settings.benchmark].dropna().index)
    last = kv_get(con, "last_processed_day")
    todo = [d for d in trading_days if last is None or d > pd.Timestamp(last)]
    if last is None:
        todo = todo[-1:]
    return [step_day(con, settings, d, closes.loc[d], trading_days) for d in todo]
