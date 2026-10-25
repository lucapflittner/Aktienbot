"""Manually (re-)sends recent rebalances to Telegram on demand -- useful to
check "was did it just restructure to" without waiting for the next
scheduled run, or to verify Telegram is wired up correctly.

Usage: python -m paper_trading.send_latest_rebalance [N]
Sends the N most recent rebalances (default 1), oldest first.
"""
import sys

from paper_trading.engine import load_state
from paper_trading.telegram_notify import send_message, format_rebalance_message


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    state = load_state()
    log = state["trade_log"]
    if not log:
        print("No rebalances recorded yet.")
        return

    start = max(0, len(log) - n)
    for idx in range(start, len(log)):
        entry = log[idx]
        previous_picks = log[idx - 1]["picks"] if idx > 0 else []
        msg = format_rebalance_message(entry, previous_picks)
        sent = send_message(msg)
        print(msg)
        print(f"[sent to Telegram: {sent}]\n---")


if __name__ == "__main__":
    main()
