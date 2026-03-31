"""Polymarket Gamma API client + market filtering.

Entry point: get_tradeable_markets() → list[MarketData]
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

import infra.config as cfg

logger = logging.getLogger(__name__)

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_CLOB_BASE = "https://clob.polymarket.com"
_PAGE_SIZE = 100
_MAX_PAGES = 3
_REQUEST_TIMEOUT = 15

# Sprint 2 hotfix overrides — don't modify infra/config.py
_VOLUME_MAX_OVERRIDE = 500_000      # was 50k, Kelly sizing handles exposure risk
_DAYS_MAX_OVERRIDE = 90             # was 30, politics/sports often 2-3 months out

# ── TTL cache ────────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}   # key → (expires_at, data)


def _cache_get(key: str) -> Any | None:
    """Return cached value if still valid, else None."""
    entry = _cache.get(key)
    if entry is None:
        logger.debug("cache_miss", extra={"key": key})
        return None
    expires_at, data = entry
    if time.monotonic() > expires_at:
        del _cache[key]
        logger.debug("cache_expired", extra={"key": key})
        return None
    logger.debug("cache_hit", extra={"key": key})
    return data


def _cache_set(key: str, data: Any, ttl: int) -> None:
    """Store value with TTL (seconds)."""
    _cache[key] = (time.monotonic() + ttl, data)


def clear_cache() -> None:
    """Clear all cached data. Useful for tests and manual resets."""
    _cache.clear()
    logger.info("cache_cleared")


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
    """Fetch up to _MAX_PAGES pages of active markets from Gamma API.

    Results are cached for CACHE_TTL_MARKETS seconds.
    """
    cached = _cache_get("raw_markets")
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    try:
        all_markets: list[dict[str, Any]] = []
        for page in range(_MAX_PAGES):
            page_data = _fetch_page(offset=page * _PAGE_SIZE)
            all_markets.extend(page_data)
            logger.debug("gamma_page_fetched", extra={"page": page, "count": len(page_data)})
            if len(page_data) < _PAGE_SIZE:
                break
        logger.info("gamma_fetch_complete", extra={"total": len(all_markets)})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_raw_markets_error", extra={"error": str(exc)})
        return []

    _cache_set("raw_markets", all_markets, cfg.CACHE_TTL_MARKETS)
    return all_markets


def fetch_price_history(market_id: str) -> dict[str, float] | None:
    """Fetch 24h price history for momentum calculation.

    Returns {"price_24h_ago": float, "current_price": float, "momentum": float}
    or None on error.  Results cached for CACHE_TTL_PRICES seconds.
    """
    cache_key = f"price_history:{market_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    try:
        response = requests.get(
            f"{_GAMMA_BASE}/prices/history",
            params={"market": market_id, "interval": "1h", "fidelity": "24"},
            timeout=5,
        )
        response.raise_for_status()
        data: Any = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "price_history_fetch_failed",
            extra={"market_id": market_id, "error": str(exc)},
        )
        return None

    if not isinstance(data, list) or len(data) < 2:
        points = len(data) if isinstance(data, list) else 0
        logger.warning(
            "price_history_insufficient_data",
            extra={"market_id": market_id, "points": points},
        )
        return None

    try:
        price_24h_ago = float(data[0].get("price", data[0].get("p", 0)))
        current_price = float(data[-1].get("price", data[-1].get("p", 0)))
    except (ValueError, TypeError, AttributeError) as exc:
        logger.warning(
            "price_history_parse_failed",
            extra={"market_id": market_id, "error": str(exc)},
        )
        return None

    result: dict[str, float] = {
        "price_24h_ago": price_24h_ago,
        "current_price": current_price,
        "momentum": current_price - price_24h_ago,
    }
    _cache_set(cache_key, result, cfg.CACHE_TTL_PRICES)
    logger.info(
        "price_history_fetched",
        extra={"market_id": market_id, "momentum": result["momentum"]},
    )
    return result


def fetch_orderbook_depth(token_id: str) -> dict[str, float] | None:
    """Fetch orderbook and compute liquidity within +/-2% of mid price.

    Returns {"bid_depth_2pct": float, "ask_depth_2pct": float, "total_liquidity": float}
    or None on error.
    """
    try:
        response = requests.get(
            f"{_CLOB_BASE}/book",
            params={"token_id": token_id},
            timeout=5,
        )
        response.raise_for_status()
        book: Any = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("orderbook_fetch_failed", extra={"token_id": token_id, "error": str(exc)})
        return None

    bids: list[dict[str, Any]] = book.get("bids", [])
    asks: list[dict[str, Any]] = book.get("asks", [])

    if not bids or not asks:
        logger.warning("orderbook_empty", extra={"token_id": token_id})
        return None

    try:
        best_bid = float(bids[0].get("price", 0))
        best_ask = float(asks[0].get("price", 0))
    except (ValueError, TypeError):
        return None

    if best_bid <= 0 or best_ask <= 0:
        return None

    mid = (best_bid + best_ask) / 2.0
    low_bound = mid * 0.98   # -2%
    high_bound = mid * 1.02  # +2%

    bid_depth = sum(
        float(b.get("size", 0))
        for b in bids
        if float(b.get("price", 0)) >= low_bound
    )
    ask_depth = sum(
        float(a.get("size", 0))
        for a in asks
        if float(a.get("price", 0)) <= high_bound
    )

    result: dict[str, float] = {
        "bid_depth_2pct": bid_depth,
        "ask_depth_2pct": ask_depth,
        "total_liquidity": bid_depth + ask_depth,
    }
    logger.info("orderbook_depth_computed", extra={"token_id": token_id, **result})
    return result


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
    """Extract lowercase tag slugs from the tags field.

    Handles both dict format ({"slug": "x", "label": "X"}) and plain strings.
    """
    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list):
        return []
    slugs: list[str] = []
    for tag in tags_raw:
        if isinstance(tag, str):
            stripped = tag.strip()
            if stripped:
                slugs.append(stripped.lower())
        elif isinstance(tag, dict):
            slug = tag.get("slug") or tag.get("label", "")
            if slug:
                slugs.append(str(slug).lower())
    return slugs


_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "politics": re.compile(
        r"election|president|vote|senate|congress|governor|mayor|parliament|"
        r"democrat|republican|primary|caucus|ballot|impeach",
        re.IGNORECASE,
    ),
    "science": re.compile(
        r"FDA|clinical.trial|study|research|peer.review|vaccine|drug.approval|"
        r"breakthrough|experiment|Nobel|laboratory",
        re.IGNORECASE,
    ),
    "sports_outcome": re.compile(
        r"win|championship|playoff|Super.Bowl|World.Cup|NBA|NFL|MLB|NHL|"
        r"match|tournament|medal|Olympics|Grand.Slam|UFC",
        re.IGNORECASE,
    ),
    "geopolitics": re.compile(
        r"sanction|treaty|NATO|invasion|ceasefire|diplomat|summit|embargo|"
        r"nuclear.deal|territorial|annexation|UN.resolution",
        re.IGNORECASE,
    ),
}


def _detect_category(question: str) -> str:
    """Detect market category from question text via keyword patterns."""
    for category, pattern in _CATEGORY_PATTERNS.items():
        if pattern.search(question):
            logger.debug(
                "category_detected",
                extra={"category": category, "question": question[:60]},
            )
            return category
    return "default"


def _primary_category(tags: list[str], question: str = "") -> str:
    """Return the first focus-matching tag, keyword-detected category, or fallback."""
    focus: list[str] = list(cfg.MARKET_FILTERS["category_focus"])
    for tag in tags:
        if _tag_in_focus(tag, focus):
            return tag
    detected = _detect_category(question)
    if detected != "default":
        return detected
    return tags[0] if tags else "default"


def _tag_in_focus(tag: str, focus: list[str]) -> bool:
    """Substring match in both directions to handle 'sports' ↔ 'sports_outcome'."""
    for f in focus:
        if f in tag or tag in f:
            return True
    return False


# ── Filtering ─────────────────────────────────────────────────────────────────

def _check_filter(market: MarketData) -> str | None:
    """Return the name of the first rejecting filter, or None if market passes."""
    f = cfg.MARKET_FILTERS
    vol_min = float(f["volume_min"])
    vol_max = float(_VOLUME_MAX_OVERRIDE)
    days_min = float(f["days_to_resolution"][0])
    days_max = float(_DAYS_MAX_OVERRIDE)
    spread_max = float(f["spread_max"])
    price_lo, price_hi = float(f["price_range"][0]), float(f["price_range"][1])
    blacklist: list[str] = list(f["category_blacklist"])
    focus: list[str] = list(f["category_focus"])

    if not (vol_min <= market.volume <= vol_max):
        return "volume"
    if not (days_min <= market.days_to_resolution <= days_max):
        return "days_to_resolution"
    if market.spread > spread_max:
        return "spread"
    if not (price_lo <= market.yes_price <= price_hi):
        return "price_range"
    if market.category in blacklist:
        return "category_blacklist"

    # Category focus: check tags first, fallback to detected category
    if not any(_tag_in_focus(tag, focus) for tag in market.tags):
        if _tag_in_focus(market.category, focus):
            logger.warning(
                "category_focus_fallback",
                extra={"market_id": market.market_id, "category": market.category},
            )
        else:
            return "category_focus"

    return None


def _passes_filters(market: MarketData) -> bool:
    """Apply all MARKET_FILTERS from config. Return True if market is tradeable."""
    reason = _check_filter(market)
    if reason is not None:
        logger.debug(
            "market_rejected",
            extra={"market_id": market.market_id, "filter": reason},
        )
    return reason is None


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
    category = _primary_category(tags, question)

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
    rejection_counts: dict[str, int] = {}

    for raw in raw_markets:
        market = parse_market(raw)
        if market is None:
            skipped_parse += 1
            continue
        reason = _check_filter(market)
        if reason is not None:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            logger.debug(
                "market_rejected",
                extra={"market_id": market.market_id, "filter": reason},
            )
            continue
        results.append(market)

    skipped_filter = sum(rejection_counts.values())
    logger.info(
        "markets_filtered",
        extra={
            "total_raw": len(raw_markets),
            "skipped_parse": skipped_parse,
            "skipped_filter": skipped_filter,
            "tradeable": len(results),
            **{f"rejected_{k}": v for k, v in rejection_counts.items()},
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
