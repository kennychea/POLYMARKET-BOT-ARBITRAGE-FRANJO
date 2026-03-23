"""Centralized configuration — all constants and secrets loaded from .env."""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Return env var value, raising RuntimeError if absent or empty."""
    value = os.getenv(key, "")
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


# ── Secrets ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")
POLYMARKET_API_KEY: str = _require("POLYMARKET_API_KEY")
POLYMARKET_PRIVATE_KEY: str = _require("POLYMARKET_PRIVATE_KEY")
PERPLEXITY_API_KEY: str = _require("PERPLEXITY_API_KEY")
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "data/polymarket.db")

# ── Trading thresholds ────────────────────────────────────────────────────────
MIN_EDGE_NET: float = 0.05
MIN_CONFIDENCE: int = 6
KELLY_FRACTION: float = 0.25
MAX_POSITION_PCT: float = 0.08          # 8% of bankroll per trade
MAX_SIMULTANEOUS_POSITIONS: int = 5
CYCLE_INTERVAL_SECONDS: int = 900       # 15 min
MIN_TRADE_SIZE: float = 3.0             # USDC (covers gas + fees)
POLYMARKET_FEE: float = 0.02            # 2% on gains

# ── Market filters ────────────────────────────────────────────────────────────
MARKET_FILTERS: dict[str, Any] = {
    "volume_min": 1_000,
    "volume_max": 50_000,               # stay below big-bot radar
    "days_to_resolution": (2, 30),
    "spread_max": 0.04,
    "price_range": (0.10, 0.90),
    "category_blacklist": ["crypto_price"],
    "category_focus": ["politics", "science", "sports_outcome", "geopolitics"],
}
