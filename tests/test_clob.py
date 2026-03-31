"""Tests for execution/clob.py — CLOB limit order wrapper."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from execution.clob import (
    cancel_order,
    compute_limit_price,
    get_best_price,
    get_open_orders,
    get_wallet_balance,
    place_limit_order,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_client() -> MagicMock:
    return MagicMock()


def _mock_orderbook(asks: list[dict[str, Any]] | None = None) -> SimpleNamespace:
    ask_objects = [SimpleNamespace(**a) for a in asks] if asks else []
    return SimpleNamespace(
        asks=ask_objects,
        bids=[],
        market="test",
        asset_id="token-1",
        timestamp="",
        min_order_size=0.01,
        neg_risk=False,
        tick_size="0.01",
        last_trade_price=0.5,
        hash="",
    )


# ── get_wallet_balance ───────────────────────────────────────────────────────

def test_get_wallet_balance_success() -> None:
    """Mock client.get_balance() returns value → float returned."""
    client = _mock_client()
    client.get_balance.return_value = "142.50"
    assert get_wallet_balance(client) == pytest.approx(142.50)


def test_get_wallet_balance_fallback_on_error() -> None:
    """Mock client.get_balance() throws → returns INITIAL_BANKROLL_USDC."""
    client = _mock_client()
    client.get_balance.side_effect = Exception("RPC error")
    with patch("execution.clob.cfg.INITIAL_BANKROLL_USDC", 100.0):
        result = get_wallet_balance(client)
    assert result == pytest.approx(100.0)


# ── compute_limit_price (pure function) ──────────────────────────────────────

def test_compute_limit_price_normal() -> None:
    """best_ask=0.55 → limit=0.555, slippage_ok=True."""
    price, ok = compute_limit_price(0.55)
    assert price == pytest.approx(0.555, abs=0.001)
    assert ok is True


def test_compute_limit_price_slippage_exceeded() -> None:
    """Large offset → slippage check fails."""
    price, ok = compute_limit_price(0.55, aggressive_offset=0.05)
    assert ok is False


# ── get_best_price ────────────────────────────────────────────────────────────

def test_get_best_price_valid_orderbook() -> None:
    """Mock orderbook with asks → returns lowest ask price."""
    client = _mock_client()
    client.get_order_book.return_value = _mock_orderbook(
        asks=[{"price": "0.60", "size": "100"}, {"price": "0.55", "size": "50"}],
    )
    assert get_best_price(client, "token-1") == pytest.approx(0.55)


def test_get_best_price_empty_orderbook() -> None:
    """Mock empty asks → returns None."""
    client = _mock_client()
    client.get_order_book.return_value = _mock_orderbook(asks=[])
    assert get_best_price(client, "token-1") is None


def test_get_best_price_api_error() -> None:
    """Mock exception → returns None."""
    client = _mock_client()
    client.get_order_book.side_effect = Exception("API down")
    assert get_best_price(client, "token-1") is None


# ── place_limit_order ─────────────────────────────────────────────────────────

def test_place_limit_order_success() -> None:
    """Normal flow → OrderResult status='placed'."""
    client = _mock_client()
    client.get_order_book.return_value = _mock_orderbook(
        asks=[{"price": "0.55", "size": "100"}],
    )
    client.create_and_post_order.return_value = {"id": "order-123"}

    result = place_limit_order(client, "token-1", "BUY", 50.0)
    assert result.status == "placed"
    assert result.order_id == "order-123"
    assert result.price is not None
    assert result.price > 0
    assert result.size_shares is not None
    assert result.size_shares > 0
    assert result.cost_usdc == 50.0


def test_place_limit_order_slippage_skip() -> None:
    """Best ask too high relative to offset → status='skipped'."""
    client = _mock_client()
    # Use a very low ask so that a huge offset triggers slippage
    client.get_order_book.return_value = _mock_orderbook(
        asks=[{"price": "0.10", "size": "100"}],
    )

    with patch("execution.clob.AGGRESSIVE_OFFSET", 0.05):
        result = place_limit_order(client, "token-1", "BUY", 50.0)

    assert result.status == "skipped"
    assert result.reason == "slippage_exceeded"


def test_place_limit_order_empty_book() -> None:
    """No asks → status='error', reason='empty_orderbook'."""
    client = _mock_client()
    client.get_order_book.return_value = _mock_orderbook(asks=[])

    result = place_limit_order(client, "token-1", "BUY", 50.0)
    assert result.status == "error"
    assert result.reason == "empty_orderbook"


def test_place_limit_order_api_exception() -> None:
    """create_and_post_order throws → status='error'."""
    client = _mock_client()
    client.get_order_book.return_value = _mock_orderbook(
        asks=[{"price": "0.55", "size": "100"}],
    )
    client.create_and_post_order.side_effect = Exception("Network error")

    result = place_limit_order(client, "token-1", "BUY", 50.0)
    assert result.status == "error"
    assert "Network error" in (result.reason or "")


# ── cancel_order ──────────────────────────────────────────────────────────────

def test_cancel_order_success() -> None:
    """Mock cancel returns ok → True."""
    client = _mock_client()
    client.cancel.return_value = True
    assert cancel_order(client, "order-123") is True


def test_cancel_order_failure() -> None:
    """Mock cancel throws → False."""
    client = _mock_client()
    client.cancel.side_effect = Exception("Not found")
    assert cancel_order(client, "order-123") is False


# ── get_open_orders ───────────────────────────────────────────────────────────

def test_get_open_orders_returns_list() -> None:
    """Mock returns orders → list."""
    client = _mock_client()
    client.get_orders.return_value = [{"id": "o1"}, {"id": "o2"}]
    orders = get_open_orders(client)
    assert len(orders) == 2


def test_get_open_orders_error_returns_empty() -> None:
    """Mock throws → empty list."""
    client = _mock_client()
    client.get_orders.side_effect = Exception("Timeout")
    assert get_open_orders(client) == []
