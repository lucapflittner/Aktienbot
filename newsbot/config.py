"""All settings in one place. Values come from environment variables, which can
also be put in a `.env` file in the project root (see `.env.example`).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader so python-dotenv isn't a hard dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _env(name, default, cast=str):
    raw = os.environ.get(name)
    return default if raw in (None, "") else cast(raw)


@dataclass
class Settings:
    # --- storage -------------------------------------------------------
    data_dir: Path = field(default_factory=lambda: Path(_env("NEWSBOT_DATA_DIR", str(ROOT / "data"))))

    # --- local LLM (any OpenAI-compatible server: Ollama, LM Studio, llama.cpp, vLLM)
    llm_base_url: str = _env("LLM_BASE_URL", "http://localhost:11434/v1")
    llm_model: str = _env("LLM_MODEL", "qwen3.6:35b-a3b")
    llm_api_key: str = _env("LLM_API_KEY", "local")
    llm_timeout_s: float = _env("LLM_TIMEOUT_S", 300.0, float)
    llm_max_input_chars: int = _env("LLM_MAX_INPUT_CHARS", 12_000, int)
    llm_temperature: float = _env("LLM_TEMPERATURE", 0.1, float)

    # --- sources -------------------------------------------------------
    # SEC requires a descriptive User-Agent with a contact address, e.g.
    # "newsbot yourname@example.com". Requests without it get blocked.
    sec_user_agent: str = _env("SEC_USER_AGENT", "")
    sec_max_pages: int = _env("SEC_MAX_PAGES", 10, int)   # 100 filings per page
    gdelt_enabled: bool = _env("GDELT_ENABLED", "1") == "1"
    gdelt_max_records: int = _env("GDELT_MAX_RECORDS", 40, int)
    rss_feeds: tuple = tuple(f for f in _env("RSS_FEEDS", "").split(",") if f.strip())

    # --- signals -------------------------------------------------------
    signal_halflife_hours: float = _env("SIGNAL_HALFLIFE_HOURS", 48.0, float)
    entry_threshold: float = _env("ENTRY_THRESHOLD", 0.5, float)
    exit_threshold: float = _env("EXIT_THRESHOLD", 0.0, float)
    min_confidence: float = _env("MIN_CONFIDENCE", 0.5, float)
    insider_min_value_usd: float = _env("INSIDER_MIN_VALUE_USD", 100_000.0, float)

    # --- paper broker --------------------------------------------------
    capital: float = _env("CAPITAL", 10_000.0, float)
    max_positions: int = _env("MAX_POSITIONS", 10, int)
    hold_days: int = _env("HOLD_DAYS", 5, int)
    spread_bps: float = _env("SPREAD_BPS", 7.5, float)
    flat_fee: float = _env("FLAT_FEE", 1.0, float)
    # minutes after a signal's timestamp before it may be acted on -- models
    # the time to notice, score and place the order. The fill is the first
    # market close at or after that moment, never an earlier price.
    reaction_minutes: int = _env("REACTION_MINUTES", 30, int)
    benchmark: str = _env("BENCHMARK", "SPY")

    # --- notifications -------------------------------------------------
    telegram_token: str = _env("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = _env("TELEGRAM_CHAT_ID", "")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "newsbot.sqlite"


SETTINGS = Settings()

# Sector ETFs used for sector-relative evaluation and for macro (world news)
# signals. Keys are yfinance's `sector` names.
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}
