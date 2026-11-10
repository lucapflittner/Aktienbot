"""Entry point run once per day (via Windows Task Scheduler) to advance the
forward paper-trading test by any new real trading days. Safe to run more
than once a day or to miss days entirely -- it only ever processes days it
hasn't seen yet, in order.

Usage: python run_daily.py
"""
import sys
from datetime import date, datetime, timezone

from paper_trading.live_data import update_live_prices
from paper_trading.engine import process_new_days, load_state
from paper_trading.telegram_notify import send_message, format_rebalance_message

# Weekends plus a Thu/Fri holiday pair are legitimately quiet; beyond that a
# quiet run means the data feed stopped delivering, not that markets are shut.
MAX_QUIET_DAYS = 5


def _warn_if_stalled():
    """"Nothing new to process" and "the price feed is broken" look identical
    from the outside -- the Actions job reports success either way. That is how
    the live record sat frozen at 2026-10-30 for eight trading days before
    anyone noticed. Once the gap stops being explainable by a closed market,
    say so on the same channel the rebalances go to.
    """
    last = load_state()["last_processed_date"]
    if not last:
        return
    quiet_days = (datetime.now(timezone.utc).date() - date.fromisoformat(last)).days
    if quiet_days <= MAX_QUIET_DAYS:
        return
    msg = (f"WARNUNG: paper_trading steht seit {last} ({quiet_days} Tage ohne "
           f"neuen Handelstag). Der Kursabruf liefert vermutlich nichts Neues mehr.")
    print(msg, file=sys.stderr)
    try:
        send_message(msg)
    except Exception as e:
        print(f"WARNING: Telegram stall alert failed ({e})", file=sys.stderr)


def main():
    print(f"=== paper_trading run_daily @ {datetime.now().isoformat(timespec='seconds')} ===")
    try:
        update_live_prices()
    except Exception as e:
        print(f"WARNING: live price fetch failed ({e}); using whatever is already cached", file=sys.stderr)

    # picks before this run's rebalance(s), so the first new rebalance (if
    # any) can still show a proper added/removed diff against it
    trade_log_before = load_state()["trade_log"]
    previous_picks = trade_log_before[-1]["picks"] if trade_log_before else []

    summaries = process_new_days()
    if not summaries:
        print("No new trading days to process.")
        _warn_if_stalled()
        return

    for s in summaries:
        if s.get("is_rebalance"):
            if "skipped" in s:
                print(f"{s['date']}: rebalance SKIPPED ({s['skipped']})")
            else:
                print(f"{s['date']}: REBALANCED -> {s['picks']} "
                      f"(trades={s['num_trades']}, cost=EUR{s['spread_cost_eur'] + s['flat_cost_eur']:.2f})")
                try:
                    send_message(format_rebalance_message(s, previous_picks))
                except Exception as e:
                    print(f"WARNING: Telegram notification failed ({e})", file=sys.stderr)
                previous_picks = s["picks"]
        else:
            print(f"{s['date']}: mark-to-market only")

    state = load_state()
    print(f"\nSince inception ({state['inception_date']}):")
    print(f"  bot cash+shares tracked in state.json; see nav_log.csv for the full daily NAV history.")


if __name__ == "__main__":
    main()
