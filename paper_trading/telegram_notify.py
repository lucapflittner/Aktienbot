"""Sends paper-trading rebalance notifications to Telegram.

Reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from the environment (set as
GitHub Actions secrets in production; for local manual runs, put them in
.env and they'll be picked up automatically if python-dotenv is installed).
Silently no-ops if either is missing, so a repo clone without Telegram set
up never breaks the daily run -- same pattern as the live-price-fetch
failure handling in run_daily.py.

Uses stdlib urllib only, no new dependency on top of what run_daily.py
already needs.
"""
import os
import urllib.request
import urllib.parse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def send_message(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
        return True
    except Exception as e:
        print(f"WARNING: Telegram notification failed ({e})")
        return False


def format_rebalance_message(detail: dict, previous_picks: list) -> str:
    picks = detail["picks"]
    added = sorted(set(picks) - set(previous_picks))
    removed = sorted(set(previous_picks) - set(picks))
    kept = sorted(set(picks) & set(previous_picks))

    lines = [
        f"*Portfolio-Umschichtung {detail['date']}*",
        f"Picks: {', '.join(picks)}",
    ]
    if previous_picks:
        lines.append(f"+ Neu: {', '.join(added) if added else '-'}")
        lines.append(f"- Raus: {', '.join(removed) if removed else '-'}")
        lines.append(f"= Gehalten: {', '.join(kept) if kept else '-'}")
    lines.append(f"Trades: {detail['num_trades']}  |  Turnover: {detail['turnover']*100:.0f}%")
    lines.append(f"Kosten: EUR {detail['spread_cost_eur'] + detail['flat_cost_eur']:.2f}")
    lines.append(f"NAV danach: EUR {detail['nav_after']:.2f}")
    return "\n".join(lines)
