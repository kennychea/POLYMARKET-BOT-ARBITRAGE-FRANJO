"""Unit tests for core/fetcher.py — no real API calls."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.fetcher import (
    MarketData,
    _parse_prices,
    _parse_tags,
    _passes_filters,
    _tag_in_focus,
    filter_markets,
    parse_market,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _future_iso(days: int = 10) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.isoformat().replace("+00:00", "Z")


def _good_raw(**overrides: Any) -> dict[str, Any]:
    """Minimal valid raw market dict that passes all filters."""
    base: dict[str, Any] = {
        "conditionId": "0xabc123",
        "question": "Will X happen before the deadline?",
        "outcomePrices": json.dumps(["0.65", "0.35"]),
        "volume": "15000.0",
        "spread": "0.02",
        "endDate": _future_iso(days=10),
        "tags": [{"slug": "politics", "label": "Politics"}],
    }
    base.update(overrides)
    return base


# ── _parse_prices ─────────────────────────────────────────────────────────────

def test_parse_prices_valid_strings() -> None:
    raw = {"outcomePrices": '["0.70", "0.30"]'}
    result = _parse_prices(raw)
    assert result == (0.70, 0.30)


def test_parse_prices_valid_list() -> None:
    raw = {"outcomePrices": [0.55, 0.45]}
    result = _parse_prices(raw)
    assert result == (0.55, 0.45)


def test_parse_prices_missing() -> None:
    assert _parse_prices({}) is None


def test_parse_prices_non_binary() -> None:
    raw = {"outcomePrices": '["0.33", "0.33", "0.34"]'}
    assert _parse_prices(raw) is None


def test_parse_prices_out_of_range() -> None:
    # price of 0.0 is invalid
    raw = {"outcomePrices": '["0.00", "1.00"]'}
    assert _parse_prices(raw) is None


def test_parse_prices_bad_json() -> None:
    raw = {"outcomePrices": "not-json"}
    assert _parse_prices(raw) is None


# ── _parse_tags ───────────────────────────────────────────────────────────────

def test_parse_tags_slug() -> None:
    raw = {"tags": [{"slug": "Politics"}, {"slug": "geopolitics"}]}
    assert _parse_tags(raw) == ["politics", "geopolitics"]


def test_parse_tags_fallback_label() -> None:
    raw = {"tags": [{"label": "Science"}]}
    assert _parse_tags(raw) == ["science"]


def test_parse_tags_empty() -> None:
    assert _parse_tags({}) == []


def test_parse_tags_malformed() -> None:
    raw = {"tags": "not-a-list"}
    assert _parse_tags(raw) == []


# ── _tag_in_focus ─────────────────────────────────────────────────────────────

def test_tag_in_focus_exact() -> None:
    assert _tag_in_focus("politics", ["politics", "science"]) is True


def test_tag_in_focus_substring_tag_in_focus() -> None:
    # "sports" is contained in focus "sports_outcome"
    assert _tag_in_focus("sports", ["sports_outcome", "science"]) is True


def test_tag_in_focus_substring_focus_in_tag() -> None:
    # focus "science" is contained in tag "science_technology"
    assert _tag_in_focus("science_technology", ["science"]) is True


def test_tag_in_focus_no_match() -> None:
    assert _tag_in_focus("crypto", ["politics", "science"]) is False


# ── parse_market ──────────────────────────────────────────────────────────────

def test_parse_market_valid() -> None:
    market = parse_market(_good_raw())
    assert market is not None
    assert market.market_id == "0xabc123"
    assert market.yes_price == pytest.approx(0.65)
    assert market.no_price == pytest.approx(0.35)
    assert market.volume == pytest.approx(15000.0)
    assert market.spread == pytest.approx(0.02)
    assert market.category == "politics"
    assert 8 < market.days_to_resolution < 12


def test_parse_market_missing_condition_id_uses_id() -> None:
    raw = _good_raw()
    del raw["conditionId"]
    raw["id"] = "fallback-id"
    market = parse_market(raw)
    assert market is not None
    assert market.market_id == "fallback-id"


def test_parse_market_missing_question() -> None:
    raw = _good_raw(question="")
    assert parse_market(raw) is None


def test_parse_market_no_prices() -> None:
    raw = _good_raw()
    del raw["outcomePrices"]
    assert parse_market(raw) is None


def test_parse_market_no_end_date() -> None:
    raw = _good_raw()
    del raw["endDate"]
    assert parse_market(raw) is None


def test_parse_market_spread_fallback_bestask_bestbid() -> None:
    raw = _good_raw(spread=None, bestBid="0.63", bestAsk="0.67")
    del raw["spread"]
    market = parse_market(raw)
    assert market is not None
    assert market.spread == pytest.approx(0.04)


def test_parse_market_spread_fallback_implicit_vig() -> None:
    # YES=0.70, NO=0.25 → implicit vig = |1 - 0.70 - 0.25| = 0.05
    raw = _good_raw(outcomePrices='["0.70", "0.25"]')
    del raw["spread"]
    market = parse_market(raw)
    assert market is not None
    assert market.spread == pytest.approx(0.05)


# ── _passes_filters ───────────────────────────────────────────────────────────

def _make_market(**kwargs: Any) -> MarketData:
    defaults: dict[str, Any] = dict(
        market_id="0x1",
        question="Q?",
        yes_price=0.65,
        no_price=0.35,
        spread=0.02,
        volume=15_000.0,
        days_to_resolution=10.0,
        end_date=datetime.now(timezone.utc) + timedelta(days=10),
        category="politics",
        tags=["politics"],
    )
    defaults.update(kwargs)
    return MarketData(**defaults)


def test_passes_filters_good() -> None:
    assert _passes_filters(_make_market()) is True


def test_passes_filters_volume_too_low() -> None:
    assert _passes_filters(_make_market(volume=500.0)) is False


def test_passes_filters_volume_too_high() -> None:
    assert _passes_filters(_make_market(volume=100_000.0)) is False


def test_passes_filters_days_too_few() -> None:
    assert _passes_filters(_make_market(days_to_resolution=1.0)) is False


def test_passes_filters_days_too_many() -> None:
    assert _passes_filters(_make_market(days_to_resolution=45.0)) is False


def test_passes_filters_spread_too_wide() -> None:
    assert _passes_filters(_make_market(spread=0.10)) is False


def test_passes_filters_price_too_low() -> None:
    assert _passes_filters(_make_market(yes_price=0.05)) is False


def test_passes_filters_price_too_high() -> None:
    assert _passes_filters(_make_market(yes_price=0.95)) is False


def test_passes_filters_blacklisted_category() -> None:
    assert _passes_filters(_make_market(category="crypto_price", tags=["crypto_price"])) is False


def test_passes_filters_no_focus_tag() -> None:
    assert _passes_filters(_make_market(category="entertainment", tags=["entertainment"])) is False


# ── filter_markets ────────────────────────────────────────────────────────────

def test_filter_markets_returns_only_valid() -> None:
    raw_list = [
        _good_raw(),                            # should pass
        _good_raw(volume="500"),                # fail: volume too low
        _good_raw(question=""),                 # fail: parse error
        _good_raw(outcomePrices='["0.95","0.05"]'),  # fail: price out of range
    ]
    results = filter_markets(raw_list)
    assert len(results) == 1
    assert results[0].market_id == "0xabc123"


def test_filter_markets_empty_input() -> None:
    assert filter_markets([]) == []


# ── fetch_raw_markets (mocked HTTP) ──────────────────────────────────────────

def test_fetch_raw_markets_single_page() -> None:
    page = [_good_raw(conditionId=f"0x{i}") for i in range(50)]
    mock_response = MagicMock()
    mock_response.json.return_value = page
    mock_response.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_response) as mock_get:
        from core.fetcher import fetch_raw_markets

        result = fetch_raw_markets()

    assert len(result) == 50
    mock_get.assert_called_once()  # stopped after first page (< PAGE_SIZE)


def test_fetch_raw_markets_non_list_response() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"error": "unexpected"}
    mock_response.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_response):
        from core.fetcher import fetch_raw_markets

        result = fetch_raw_markets()

    assert result == []
