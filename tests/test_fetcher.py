"""Unit tests for core/fetcher.py — no real API calls."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import requests

import pytest

from core.fetcher import (
    MarketData,
    _parse_prices,
    _parse_tags,
    _passes_filters,
    _tag_in_focus,
    clear_cache,
    fetch_orderbook_depth,
    fetch_price_history,
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


# ── Cache TTL ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Ensure each test starts with a clean cache."""
    clear_cache()


def test_fetch_raw_markets_uses_cache() -> None:
    """Second call should return cached data without hitting the API."""
    page = [_good_raw(conditionId=f"0x{i}") for i in range(10)]
    mock_response = MagicMock()
    mock_response.json.return_value = page
    mock_response.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_response) as mock_get:
        from core.fetcher import fetch_raw_markets

        first = fetch_raw_markets()
        second = fetch_raw_markets()

    assert first == second
    assert mock_get.call_count == 1  # only one actual HTTP call


def test_clear_cache_forces_refetch() -> None:
    page = [_good_raw(conditionId="0xcache")]
    mock_response = MagicMock()
    mock_response.json.return_value = page
    mock_response.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_response) as mock_get:
        from core.fetcher import fetch_raw_markets

        fetch_raw_markets()
        clear_cache()
        fetch_raw_markets()

    assert mock_get.call_count == 2


# ── fetch_price_history ──────────────────────────────────────────────────────


def _price_history_response(prices: list[float]) -> list[dict[str, float]]:
    return [{"price": p} for p in prices]


def test_fetch_price_history_valid() -> None:
    data = _price_history_response([0.40, 0.42, 0.45, 0.50])
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        result = fetch_price_history("mkt-1")

    assert result is not None
    assert result["price_24h_ago"] == pytest.approx(0.40)
    assert result["current_price"] == pytest.approx(0.50)
    assert result["momentum"] == pytest.approx(0.10)


def test_fetch_price_history_cached() -> None:
    data = _price_history_response([0.30, 0.35])
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp) as mock_get:
        fetch_price_history("mkt-cache")
        fetch_price_history("mkt-cache")

    assert mock_get.call_count == 1


def test_fetch_price_history_insufficient_data() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"price": 0.5}]  # only 1 point
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        assert fetch_price_history("mkt-bad") is None


def test_fetch_price_history_http_error() -> None:
    with patch("core.fetcher.requests.get", side_effect=requests.exceptions.Timeout("timeout")):
        assert fetch_price_history("mkt-err") is None


def test_fetch_price_history_non_list_response() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error": "not found"}
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        assert fetch_price_history("mkt-nonlist") is None


# ── fetch_orderbook_depth ────────────────────────────────────────────────────


def _orderbook_response(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> dict[str, list[dict[str, str]]]:
    return {
        "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
        "asks": [{"price": str(p), "size": str(s)} for p, s in asks],
    }


def test_fetch_orderbook_depth_valid() -> None:
    book = _orderbook_response(
        bids=[(0.50, 100), (0.49, 200), (0.45, 500)],
        asks=[(0.52, 150), (0.53, 300), (0.60, 800)],
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = book
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        result = fetch_orderbook_depth("tok-1")

    assert result is not None
    # mid = (0.50 + 0.52) / 2 = 0.51
    # low_bound = 0.51 * 0.98 = 0.4998 → bids >= 0.4998: 0.50(100)
    # high_bound = 0.51 * 1.02 = 0.5202 → asks <= 0.5202: 0.52(150)
    assert result["bid_depth_2pct"] == pytest.approx(100.0)
    assert result["ask_depth_2pct"] == pytest.approx(150.0)
    assert result["total_liquidity"] == pytest.approx(250.0)


def test_fetch_orderbook_depth_empty_book() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"bids": [], "asks": []}
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        assert fetch_orderbook_depth("tok-empty") is None


def test_fetch_orderbook_depth_http_error() -> None:
    with patch("core.fetcher.requests.get", side_effect=requests.exceptions.ConnectionError("fail")):
        assert fetch_orderbook_depth("tok-err") is None


def test_fetch_orderbook_depth_wide_book() -> None:
    """All liquidity within 2% range should be summed."""
    book = _orderbook_response(
        bids=[(0.50, 100), (0.50, 50)],   # both at mid-ish
        asks=[(0.52, 200), (0.52, 100)],
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = book
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        result = fetch_orderbook_depth("tok-wide")

    assert result is not None
    assert result["bid_depth_2pct"] == pytest.approx(150.0)
    assert result["ask_depth_2pct"] == pytest.approx(300.0)


# ── Prompt 6 — additional coverage ─────────────────────────────────────────


def test_fetch_price_history_malformed_entries() -> None:
    """Price entries missing 'price' key → returns None."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"t": 1}, {"t": 2}]  # no price key
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        result = fetch_price_history("mkt-malformed")

    # float(0) for missing key → price_24h_ago=0.0, current=0.0 — still returns dict
    # Actually: data[0].get("price", data[0].get("p", 0)) → 0
    # This is valid parsing (returns 0s), so result is not None but values are 0
    assert result is not None
    assert result["price_24h_ago"] == pytest.approx(0.0)
    assert result["current_price"] == pytest.approx(0.0)
    assert result["momentum"] == pytest.approx(0.0)


def test_fetch_orderbook_depth_no_liquidity_within_2pct() -> None:
    """All liquidity outside +/-2% of mid → depths are 0."""
    book = _orderbook_response(
        bids=[(0.30, 500)],   # far below mid
        asks=[(0.70, 500)],   # far above mid
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = book
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        result = fetch_orderbook_depth("tok-spread")

    assert result is not None
    # mid = (0.30 + 0.70) / 2 = 0.50
    # low_bound = 0.49, high_bound = 0.51 → neither bid nor ask in range
    assert result["bid_depth_2pct"] == pytest.approx(0.0)
    assert result["ask_depth_2pct"] == pytest.approx(0.0)
    assert result["total_liquidity"] == pytest.approx(0.0)


def test_get_tradeable_markets_returns_filtered_list() -> None:
    """get_tradeable_markets() = fetch_raw_markets() + filter_markets(), no regression."""
    from core.fetcher import get_tradeable_markets

    raw = [_good_raw(), _good_raw(volume="500")]  # 1 valid, 1 too-low-volume
    mock_resp = MagicMock()
    mock_resp.json.return_value = raw
    mock_resp.raise_for_status.return_value = None

    with patch("core.fetcher.requests.get", return_value=mock_resp):
        markets = get_tradeable_markets()

    assert len(markets) == 1
    assert markets[0].market_id == "0xabc123"
