"""Polymarket Gamma API client + market filtering.

Entry point: get_tradeable_markets() → list[MarketData]
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

import infra.config as cfg

logger = logging.getLogger(__name__)

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_PAGE_SIZE = 100
_MAX_PAGES = 3
_REQUEST_TIMEOUT = 15


@dataclass
class MarketData:
    """Parsed, filter-passing market ready for scoring."""

    market_id: str          # conditionId (used by CLOB)
    question: str
    yes_price: float        # mid price for YES (0.0–1.0)
    no_price: float         # mid price for NO  (0.0–1.0)
    spread: float           # bid-ask spread
    volume: float           # total volume in USDC
    days_to_resolution: float
    end_date: datetime
    category: str           # primary focus tag slug
    tags: list[str] = field(default_factory=list)


# ── API layer ─────────────────────────────────────────────────────────────────

def _fetch_page(offset: int) -> list[dict[str, Any]]:
    """Fetch one page of active, open markets from Gamma API."""
    response = requests.get(
        f"{_GAMMA_BASE}/markets",
        params={
            "active": "true",
            "closed": "false",
            "limit": str(_PAGE_SIZE),
            "offset": str(offset),
        },
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data: Any = response.json()
    return data if isinstance(data, list) else []


def fetch_raw_markets() -> list[dict[str, Any]]:
    """Fetch up to _MAX_PAGES pages of active markets from Gamma API."""
    all_markets: list[dict[str, Any]] = []
    for page in range(_MAX_PAGES):
        page_data = _fetch_page(offset=page * _PAGE_SIZE)
        all_markets.extend(page_data)
        logger.debug("gamma_page_fetched", extra={"page": page, "count": len(page_data)})
        if len(page_data) < _PAGE_SIZE:
            break
    logger.info("gamma_fetch_complete", extra={"total": len(all_markets)})
    return all_markets


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_float_field(raw: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    """Extract a float from the first matching key; handles string-encoded values."""
    for key in keys:
        val = raw.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return default


def _parse_prices(raw: dict[str, Any]) -> tuple[float, float] | None:
    """Extract (yes_price, no_price) from outcomePrices.

    Returns None if the market is not binary or prices are out of range.
    """
    prices_raw = raw.get("outcomePrices")
    if not prices_raw:
        return None
    try:
        prices: list[Any] = (
            json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        )
        if len(prices) != 2:
            return None
        yes = float(prices[0])
        no = float(prices[1])
        if not (0.0 < yes < 1.0 and 0.0 < no < 1.0):
            return None
        return yes, no
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _parse_end_date(raw: dict[str, Any]) -> datetime | None:
    """Parse endDate field into a UTC-aware datetime."""
    end_str = raw.get("endDate") or raw.get("end_date_iso")
    if not end_str:
        return None
    try:
        return datetime.fromisoformat(str(end_str).replace("Z", "+00:00")).astimezone(
            UTC
        )
    except (ValueError, AttributeError):
        return None


def _parse_tags(raw: dict[str, Any]) -> list[str]:
    """Extract lowercase tag slugs from the tags field."""
    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list):
        return []
    slugs: list[str] = []
    for tag in tags_raw:
        if isinstance(tag, dict):
            slug = tag.get("slug") or tag.get("label", "")
            if slug:
                slugs.append(str(slug).lower())
    return slugs


def _primary_category(tags: list[str]) -> str:
    """Return the first focus-matching tag, else the first tag, else 'unknown'."""
    focus: list[str] = list(cfg.MARKET_FILTERS["category_focus"])
    for tag in tags:
        if _tag_in_focus(tag, focus):
            return tag
    return tags[0] if tags else "unknown"


def _tag_in_focus(tag: str, focus: list[str]) -> bool:
    """Substring match in both directions to handle 'sports' ↔ 'sports_outcome'."""
    for f in focus:
        if f in tag or tag in f:
            return True
    return False


# ── Filtering ─────────────────────────────────────────────────────────────────

def _passes_filters(market: MarketData) -> bool:
    """Apply all MARKET_FILTERS from config. Return True if market is tradeable."""
    f = cfg.MARKET_FILTERS
    vol_min = float(f["volume_min"])
    vol_max = float(f["volume_max"])
    days_min, days_max = float(f["days_to_resolution"][0]), float(f["days_to_resolution"][1])
    spread_max = float(f["spread_max"])
    price_lo, price_hi = float(f["price_range"][0]), float(f["price_range"][1])
    blacklist: list[str] = list(f["category_blacklist"])
    focus: list[str] = list(f["category_focus"])

    if not (vol_min <= market.volume <= vol_max):
        return False
    if not (days_min <= market.days_to_resolution <= days_max):
        return False
    if market.spread > spread_max:
        return False
    if not (price_lo <= market.yes_price <= price_hi):
        return False
    if market.category in blacklist:
        return False
    if not any(_tag_in_focus(tag, focus) for tag in market.tags):
        return False
    return True


# ── Public parse + pipeline ───────────────────────────────────────────────────

def parse_market(raw: dict[str, Any]) -> MarketData | None:
    """Parse one raw API dict into MarketData. Returns None if invalid or non-binary."""
    market_id = str(raw.get("conditionId") or raw.get("id", "")).strip()
    if not market_id:
        return None

    question = str(raw.get("question", "")).strip()
    if not question:
        return None

    prices = _parse_prices(raw)
    if prices is None:
        return None
    yes_price, no_price = prices

    end_date = _parse_end_date(raw)
    if end_date is None:
        return None

    now = datetime.now(UTC)
    days_to_resolution = (end_date - now).total_seconds() / 86_400

    volume = _parse_float_field(raw, "volume", "volumeNum")

    # Spread: prefer explicit field, then bestAsk-bestBid, then implicit vig
    spread = _parse_float_field(raw, "spread")
    if spread == 0.0:
        best_ask = _parse_float_field(raw, "bestAsk")
        best_bid = _parse_float_field(raw, "bestBid")
        spread = (
            best_ask - best_bid
            if best_ask > 0 and best_bid > 0
            else abs(1.0 - yes_price - no_price)
        )

    tags = _parse_tags(raw)
    category = _primary_category(tags)

    return MarketData(
        market_id=market_id,
        question=question,
        yes_price=yes_price,
        no_price=no_price,
        spread=spread,
        volume=volume,
        days_to_resolution=days_to_resolution,
        end_date=end_date,
        category=category,
        tags=tags,
    )


def filter_markets(raw_markets: list[dict[str, Any]]) -> list[MarketData]:
    """Parse and filter raw API markets into tradeable MarketData."""
    results: list[MarketData] = []
    skipped_parse = 0
    skipped_filter = 0

    for raw in raw_markets:
        market = parse_market(raw)
        if market is None:
            skipped_parse += 1
            continue
        if not _passes_filters(market):
            skipped_filter += 1
            continue
        results.append(market)

    logger.info(
        "markets_filtered",
        extra={
            "total_raw": len(raw_markets),
            "skipped_parse": skipped_parse,
            "skipped_filter": skipped_filter,
            "tradeable": len(results),
        },
    )
    return results


def get_tradeable_markets() -> list[MarketData]:
    """Main entry point: fetch + filter Polymarket markets.

    Called by pipeline/orchestrator.py every cycle.
    """
    raw = fetch_raw_markets()
    return filter_markets(raw)


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint

    logging.basicConfig(level=logging.INFO)
    markets = get_tradeable_markets()
    print(f"\nTradeable markets: {len(markets)}\n")
    for m in markets[:5]:
        pprint.pprint(m)
        print()
