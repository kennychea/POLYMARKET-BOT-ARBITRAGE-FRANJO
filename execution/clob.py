"""CLOB order wrapper — limit orders only, with slippage protection."""
from __future__ import annotations

import logging
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

from infra.config import POLYMARKET_API_KEY, POLYMARKET_PRIVATE_KEY
from infra.types import OrderResult

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137
AGGRESSIVE_OFFSET = 0.005    # slightly above best_ask for fill
MAX_SLIPPAGE = 0.02          # 2% max above current price


def init_clob_client() -> ClobClient:
    """Initialize py-clob-client with API key + private key from config.

    Chain ID: Polygon (137). Re-raises on error (can't trade without client).
    """
    try:
        client = ClobClient(
            host=CLOB_HOST,
            chain_id=POLYGON_CHAIN_ID,
            key=POLYMARKET_PRIVATE_KEY,
        )
        logger.info("clob_client_initialized", extra={"chain_id": POLYGON_CHAIN_ID})
        return client
    except Exception:
        logger.error("clob_client_init_failed", extra={"chain_id": POLYGON_CHAIN_ID})
        raise


def get_best_price(client: ClobClient, token_id: str) -> float | None:
    """Fetch orderbook and return the lowest ask price.

    Returns None if orderbook is empty or API fails.
    """
    try:
        book = client.get_order_book(token_id)
        asks: list[Any] = book.asks if book.asks else []
        if not asks:
            return None
        prices = [float(a.price) if hasattr(a, "price") else float(a["price"]) for a in asks]
        return min(prices)
    except Exception:
        logger.warning("get_best_price_failed", extra={"token_id": token_id})
        return None


def compute_limit_price(
    best_ask: float,
    aggressive_offset: float = AGGRESSIVE_OFFSET,
    max_slippage: float = MAX_SLIPPAGE,
) -> tuple[float, bool]:
    """Compute limit price with slippage check.

    Returns (limit_price, slippage_ok). Pure function.
    """
    limit_price = round(best_ask + aggressive_offset, 4)
    slippage_ok = limit_price <= best_ask * (1 + max_slippage)
    return limit_price, slippage_ok


def place_limit_order(
    client: ClobClient,
    token_id: str,
    side: str,
    size_usdc: float,
) -> OrderResult:
    """Place a GTC limit order on the CLOB.

    Flow: get best price → check slippage → compute shares → post order.
    Returns OrderResult with status 'placed', 'skipped', or 'error'.
    """
    try:
        best_ask = get_best_price(client, token_id)
        if best_ask is None:
            result = OrderResult(
                status="error", order_id=None, price=None,
                size_shares=None, cost_usdc=None, reason="empty_orderbook",
            )
            logger.info("order_attempt", extra={
                "token_id": token_id, "side": side,
                "size_usdc": size_usdc, "status": result.status,
                "reason": result.reason,
            })
            return result

        limit_price, slippage_ok = compute_limit_price(best_ask)
        if not slippage_ok:
            result = OrderResult(
                status="skipped", order_id=None, price=limit_price,
                size_shares=None, cost_usdc=size_usdc, reason="slippage_exceeded",
            )
            logger.info("order_attempt", extra={
                "token_id": token_id, "side": side,
                "price": limit_price, "size_usdc": size_usdc,
                "status": result.status, "reason": result.reason,
            })
            return result

        size_shares = round(size_usdc / limit_price, 4)

        order_args = OrderArgs(
            token_id=token_id,
            price=limit_price,
            size=size_shares,
            side=side,
        )
        response = client.create_and_post_order(order_args)

        order_id: str | None = None
        if isinstance(response, dict):
            order_id = response.get("id") or response.get("orderID")
        elif hasattr(response, "id"):
            order_id = response.id

        result = OrderResult(
            status="placed",
            order_id=order_id,
            price=limit_price,
            size_shares=size_shares,
            cost_usdc=size_usdc,
            reason=None,
        )
        logger.info("order_placed", extra={
            "token_id": token_id, "side": side,
            "price": limit_price, "size_usdc": size_usdc,
            "size_shares": size_shares, "order_id": order_id,
            "status": result.status,
        })
        return result

    except Exception as exc:
        result = OrderResult(
            status="error", order_id=None, price=None,
            size_shares=None, cost_usdc=None, reason=str(exc),
        )
        logger.error("order_failed", extra={
            "token_id": token_id, "side": side,
            "size_usdc": size_usdc, "error": str(exc),
        })
        return result


def cancel_order(client: ClobClient, order_id: str) -> bool:
    """Cancel a GTC order by ID. Returns True on success, False on failure."""
    try:
        client.cancel(order_id)
        logger.info("order_cancelled", extra={"order_id": order_id, "success": True})
        return True
    except Exception:
        logger.warning("order_cancel_failed", extra={"order_id": order_id, "success": False})
        return False


def get_open_orders(client: ClobClient) -> list[dict[str, Any]]:
    """Return all open GTC orders. Returns empty list on failure."""
    try:
        orders = client.get_orders()
        if isinstance(orders, list):
            return orders
        return []
    except Exception:
        logger.warning("get_open_orders_failed")
        return []
