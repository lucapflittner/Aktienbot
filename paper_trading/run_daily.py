"""Entry point run once per day (via Windows Task Scheduler) to advance the
forward paper-trading test by any new real trading days. Safe to run more
than once a day or to miss days entirely -- it only ever processes days it
hasn't seen yet, in order.

Usage: python run_daily.py
"""
import sys
from datetime import datetime

from paper_trading.live_data import update_live_prices
from paper_trading.engine import process_new_days, load_state


def main():
    print(f"=== paper_trading run_daily @ {datetime.now().isoformat(timespec='seconds')} ===")
    try:
        update_live_prices()
    except Exception as e:
        print(f"WARNING: live price fetch failed ({e}); using whatever is already cached", file=sys.stderr)

    summaries = process_new_days()
    if not summaries:
        print("No new trading days to process.")
        return

    for s in summaries:
        if s.get("is_rebalance"):
            if "skipped" in s:
                print(f"{s['date']}: rebalance SKIPPED ({s['skipped']})")
            else:
                print(f"{s['date']}: REBALANCED -> {s['picks']} "
                      f"(trades={s['num_trades']}, cost=EUR{s['spread_cost_eur'] + s['flat_cost_eur']:.2f})")
        else:
            print(f"{s['date']}: mark-to-market only")

    state = load_state()
    print(f"\nSince inception ({state['inception_date']}):")
    print(f"  bot cash+shares tracked in state.json; see nav_log.csv for the full daily NAV history.")


if __name__ == "__main__":
    main()
