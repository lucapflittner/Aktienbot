"""Telegram messages (same setup as the Aktienbot paper trader: set
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID). Silently does nothing without them."""
import requests


def send(settings, text: str) -> bool:
    if not settings.telegram_token or not settings.telegram_chat_id:
        return False
    try:
        requests.post(f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
                      data={"chat_id": settings.telegram_chat_id, "text": text}, timeout=10)
        return True
    except requests.RequestException as e:
        print(f"WARNING: Telegram failed ({e})")
        return False
