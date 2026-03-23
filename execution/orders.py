"""Order lifecycle tracking — fill polling, stale cleanup, DB recording."""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from py_clob_client.client import ClobClient

from execution.clob import cancel_order, get_open_orders
from infra.db import log_trade
from infra.telegram import format_trade_alert, send_alert
from infra.types import OrderResult, TradingSignal

logger = logging.getLogger(__name__)


def check_fill_status(client: ClobClient, order_id: str) -> str:
    """Single check of order status via the CLOB API.

    Returns one of: 'filled', 'partial', 'open', 'cancelled', 'unknown'.
    """
    try:
        order = client.get_order(order_id)
        if isinstance(order, dict):
            status = order.get("status", "").lower()
        elif hasattr(order, "status"):
            status = str(order.status).lower()
        else:
            return "unknown"

        if status in ("matched", "filled"):
            return "filled"
        if status in ("open", "live", "active"):
            return "open"
        if status in ("cancelled", "canceled"):
            return "cancelled"
        if "partial" in status:
            return "partial"
        return "unknown"
    except Exception as exc:
        logger.warning("check_fill_status_error", extra={
            "order_id": order_id, "error": str(exc),
        })
        return "unknown"


def track_order_fill(
    client: ClobClient,
    order_id: str,
    timeout_seconds: int = 300,
    poll_interval: int = 15,
) -> str:
    """Poll order status until terminal state or timeout.

    Returns 'filled', 'cancelled', 'timeout', or 'error'.
    """
    start = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start
            status = check_fill_status(client, order_id)

            logger.info("order_poll", extra={
                "order_id": order_id, "status": status,
                "elapsed": round(elapsed, 1),
            })

            if status in ("filled", "cancelled"):
                return status

            if elapsed >= timeout_seconds:
                cancel_order(client, order_id)
                logger.info("order_timeout", extra={
                    "order_id": order_id, "elapsed": round(elapsed, 1),
                })
                return "timeout"

            time.sleep(poll_interval)
    except Exception as exc:
        logger.error("track_order_error", extra={
            "order_id": order_id, "error": str(exc),
        })
        cancel_order(client, order_id)
        return "error"


def cancel_stale_orders(
    client: ClobClient,
    max_age_minutes: int = 60,
) -> int:
    """Cancel open orders older than max_age_minutes.

    Returns count of successfully cancelled orders.
    If timestamps are unavailable, cancels all open orders as safety fallback.
    """
    orders = get_open_orders(client)
    if not orders:
        logger.info("stale_orders_cleanup", extra={"cancelled": 0, "checked": 0})
        return 0

    now = datetime.now(timezone.utc)
    cancelled = 0

    for order in orders:
        order_id = _extract_order_id(order)
        if order_id is None:
            continue

        should_cancel = _is_stale(order, now, max_age_minutes)

        if should_cancel and cancel_order(client, order_id):
            cancelled += 1

    logger.info("stale_orders_cleanup", extra={
        "cancelled": cancelled, "checked": len(orders),
    })
    return cancelled


def record_fill(
    conn: sqlite3.Connection,
    signal: TradingSignal,
    order_result: OrderResult,
) -> int | None:
    """Record a filled order to DB and send Telegram alert.

    Returns trade_id on success, None on failure. Never crashes.
    """
    trade_id: int | None = None

    try:
        trade_id = log_trade(
            signal,
            size_usdc=order_result.cost_usdc or 0.0,
            entry_price=order_result.price or 0.0,
        )
    except Exception as exc:
        logger.error("record_fill_db_error", extra={
            "market_id": signal.market_id, "error": str(exc),
        })
        return None

    try:
        msg = format_trade_alert(
            signal,
            size_usdc=order_result.cost_usdc or 0.0,
            entry_price=order_result.price or 0.0,
        )
        send_alert(msg)
    except Exception as exc:
        logger.warning("record_fill_telegram_error", extra={
            "trade_id": trade_id, "error": str(exc),
        })

    logger.info("fill_recorded", extra={
        "trade_id": trade_id, "market_id": signal.market_id,
    })
    return trade_id


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_order_id(order: dict[str, Any]) -> str | None:
    """Extract order ID from an order dict."""
    return order.get("id") or order.get("orderID") or order.get("order_id")


def _is_stale(order: dict[str, Any], now: datetime, max_age_minutes: int) -> bool:
    """Check if an order is older than max_age_minutes. Defaults to True if no timestamp."""
    ts_raw = order.get("timestamp") or order.get("created_at")
    if ts_raw is None:
        return True  # safety fallback

    try:
        if isinstance(ts_raw, (int, float)):
            created = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
        else:
            ts_str = str(ts_raw).replace("Z", "+00:00")
            created = datetime.fromisoformat(ts_str)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        age_minutes = (now - created).total_seconds() / 60
        return age_minutes > max_age_minutes
    except (ValueError, TypeError):
        return True  # can't parse → cancel to be safe
