"""Prints the current forward paper-trading status: NAV, cumulative return,
annualized return so far, current holdings, and how it compares to the
buy-and-hold benchmark tracked in parallel.

Usage: python report.py
"""
import pandas as pd

from paper_trading.engine import load_state, NAV_LOG_PATH


def main():
    state = load_state()
    if state["inception_date"] is None:
        print("No paper-trading history yet -- run run_daily.py first.")
        return

    log = pd.read_csv(NAV_LOG_PATH, parse_dates=["date"])
    inception = pd.Timestamp(state["inception_date"])
    days_running = (log["date"].iloc[-1] - inception).days
    years_running = max(days_running / 365.25, 1 / 365.25)

    last = log.iloc[-1]
    bot_ann = (1 + last["bot_cum_return"]) ** (1 / years_running) - 1
    bench_ann = (1 + last["bench_cum_return"]) ** (1 / years_running) - 1

    print(f"=== Paper-trading status (forward test, never seen by autoresearch) ===")
    print(f"Inception: {inception.date()}  |  Last update: {last['date'].date()}  |  {days_running} days running")
    print(f"Rebalances so far: {int(log['is_rebalance'].sum())}")
    print()
    print(f"{'':20s}{'Bot':>15s}{'Buy&Hold':>15s}")
    print(f"{'NAV (EUR)':20s}{last['bot_nav']:>15.2f}{last['bench_nav']:>15.2f}")
    print(f"{'Cumulative return':20s}{last['bot_cum_return']*100:>14.2f}%{last['bench_cum_return']*100:>14.2f}%")
    print(f"{'Annualized so far':20s}{bot_ann*100:>14.2f}%{bench_ann*100:>14.2f}%")
    print()
    if days_running < 60:
        print("NOTE: fewer than ~2 months of data -- annualized figures are noisy and not meaningful yet.")

    print("\nCurrent bot holdings:")
    shares = state["bot"]["shares"]
    if shares:
        for t, n in sorted(shares.items(), key=lambda kv: -kv[1]):
            print(f"  {t:8s} {n:.4f} shares")
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
