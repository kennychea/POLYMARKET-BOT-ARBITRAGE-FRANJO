"""Tests for execution/orders.py — order lifecycle tracking."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from execution.orders import (
    cancel_stale_orders,
    check_fill_status,
    record_fill,
    track_order_fill,
)
from infra.types import OrderResult, TradingSignal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_client() -> MagicMock:
    return MagicMock()


def _make_signal() -> TradingSignal:
    return TradingSignal(
        market_id="mkt-1",
        question="Will X happen?",
        side="YES",
        agent_probability=0.60,
        market_probability=0.50,
        edge_net=0.08,
        confidence=7,
        tradeable=True,
        news_context="test",
        timestamp=datetime.now(timezone.utc),
    )


def _make_order_result() -> OrderResult:
    return OrderResult(
        status="placed",
        order_id="order-123",
        price=0.555,
        size_shares=90.09,
        cost_usdc=50.0,
        reason=None,
    )


def _make_db() -> sqlite3.Connection:
    """In-memory DB with trades table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT NOT NULL,
            market_id           TEXT NOT NULL,
            question            TEXT NOT NULL,
            side                TEXT NOT NULL,
            size_usdc           REAL NOT NULL,
            entry_price         REAL NOT NULL,
            agent_probability   REAL NOT NULL,
            market_probability  REAL NOT NULL,
            edge_net            REAL NOT NULL,
            confidence          INTEGER NOT NULL,
            order_id            TEXT NOT NULL DEFAULT '',
            size_shares         REAL NOT NULL DEFAULT 0.0,
            status              TEXT NOT NULL DEFAULT 'open',
            exit_price          REAL,
            pnl                 REAL,
            resolution_date     TEXT
        )
    """)
    conn.commit()
    return conn


# ── check_fill_status ─────────────────────────────────────────────────────────

def test_check_fill_status_filled() -> None:
    """Mock client.get_order returns filled status → 'filled'."""
    client = _mock_client()
    client.get_order.return_value = {"status": "matched"}
    assert check_fill_status(client, "order-1") == "filled"


def test_check_fill_status_open() -> None:
    """Mock returns open → 'open'."""
    client = _mock_client()
    client.get_order.return_value = {"status": "live"}
    assert check_fill_status(client, "order-1") == "open"


def test_check_fill_status_api_error() -> None:
    """Mock throws → 'unknown'."""
    client = _mock_client()
    client.get_order.side_effect = Exception("API down")
    assert check_fill_status(client, "order-1") == "unknown"


# ── track_order_fill ──────────────────────────────────────────────────────────

@patch("execution.orders.time.sleep")
def test_track_order_fill_immediate_fill(mock_sleep: MagicMock) -> None:
    """First poll returns 'filled' → returns 'filled', no sleep."""
    client = _mock_client()
    client.get_order.return_value = {"status": "matched"}
    result = track_order_fill(client, "order-1", timeout_seconds=60, poll_interval=5)
    assert result == "filled"
    mock_sleep.assert_not_called()


@patch("execution.orders.time.sleep")
def test_track_order_fill_fills_after_two_polls(mock_sleep: MagicMock) -> None:
    """First poll 'open', second poll 'filled' → returns 'filled'."""
    client = _mock_client()
    client.get_order.side_effect = [
        {"status": "live"},
        {"status": "matched"},
    ]
    result = track_order_fill(client, "order-1", timeout_seconds=60, poll_interval=5)
    assert result == "filled"
    assert mock_sleep.call_count == 1


@patch("execution.orders.time.monotonic")
@patch("execution.orders.time.sleep")
def test_track_order_fill_timeout(mock_sleep: MagicMock, mock_monotonic: MagicMock) -> None:
    """Always returns 'open', times out → cancels order, returns 'timeout'."""
    client = _mock_client()
    client.get_order.return_value = {"status": "live"}
    # First call: start=0, second call: elapsed=3 (past timeout of 2)
    mock_monotonic.side_effect = [0.0, 3.0]
    result = track_order_fill(client, "order-1", timeout_seconds=2, poll_interval=1)
    assert result == "timeout"
    client.cancel.assert_called_once_with("order-1")


@patch("execution.orders.time.sleep")
def test_track_order_fill_already_cancelled(mock_sleep: MagicMock) -> None:
    """First poll returns 'cancelled' → returns 'cancelled'."""
    client = _mock_client()
    client.get_order.return_value = {"status": "cancelled"}
    result = track_order_fill(client, "order-1", timeout_seconds=60, poll_interval=5)
    assert result == "cancelled"
    mock_sleep.assert_not_called()


# ── cancel_stale_orders ───────────────────────────────────────────────────────

def test_cancel_stale_orders_cancels_old() -> None:
    """2 old orders + 1 fresh → cancels 2, returns 2."""
    client = _mock_client()
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(minutes=120)).isoformat()
    fresh_ts = (now - timedelta(minutes=10)).isoformat()

    with patch("execution.orders.get_open_orders", return_value=[
        {"id": "o1", "timestamp": old_ts},
        {"id": "o2", "timestamp": old_ts},
        {"id": "o3", "timestamp": fresh_ts},
    ]):
        with patch("execution.orders.cancel_order", return_value=True) as mock_cancel:
            count = cancel_stale_orders(client, max_age_minutes=60)

    assert count == 2
    assert mock_cancel.call_count == 2


def test_cancel_stale_orders_none_stale() -> None:
    """All orders fresh → cancels 0."""
    client = _mock_client()
    now = datetime.now(timezone.utc)
    fresh_ts = (now - timedelta(minutes=5)).isoformat()

    with patch("execution.orders.get_open_orders", return_value=[
        {"id": "o1", "timestamp": fresh_ts},
    ]):
        with patch("execution.orders.cancel_order") as mock_cancel:
            count = cancel_stale_orders(client, max_age_minutes=60)

    assert count == 0
    mock_cancel.assert_not_called()


def test_cancel_stale_orders_empty() -> None:
    """No open orders → returns 0."""
    client = _mock_client()
    with patch("execution.orders.get_open_orders", return_value=[]):
        count = cancel_stale_orders(client)
    assert count == 0


# ── record_fill ───────────────────────────────────────────────────────────────

@patch("execution.orders.send_alert")
@patch("execution.orders.log_trade", return_value=42)
def test_record_fill_success(mock_log: MagicMock, mock_alert: MagicMock) -> None:
    """Mock DB + Telegram → returns trade_id (int)."""
    conn = _make_db()
    signal = _make_signal()
    order_result = _make_order_result()
    trade_id = record_fill(conn, signal, order_result)
    assert trade_id == 42
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args
    assert call_kwargs[1]["order_id"] == "order-123"
    assert call_kwargs[1]["size_shares"] == pytest.approx(90.09)
    mock_alert.assert_called_once()
    conn.close()


@patch("execution.orders.send_alert")
@patch("execution.orders.log_trade", side_effect=sqlite3.Error("DB locked"))
def test_record_fill_db_error(mock_log: MagicMock, mock_alert: MagicMock) -> None:
    """Mock DB throws → returns None, doesn't crash."""
    conn = _make_db()
    signal = _make_signal()
    order_result = _make_order_result()
    trade_id = record_fill(conn, signal, order_result)
    assert trade_id is None
    mock_alert.assert_not_called()
    conn.close()


@patch("execution.orders.send_alert", side_effect=Exception("Telegram down"))
@patch("execution.orders.log_trade", return_value=42)
def test_record_fill_telegram_error(mock_log: MagicMock, mock_alert: MagicMock) -> None:
    """Mock Telegram throws → still returns trade_id (DB succeeded)."""
    conn = _make_db()
    signal = _make_signal()
    order_result = _make_order_result()
    trade_id = record_fill(conn, signal, order_result)
    assert trade_id == 42
    conn.close()
