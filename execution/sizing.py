"""Position sizing — Kelly fractional + exposure checks + circuit breaker."""
from __future__ import annotations

import logging
import sqlite3

from infra.config import (
    KELLY_FRACTION,
    MAX_POSITION_PCT,
    MAX_SIMULTANEOUS_POSITIONS,
    MIN_TRADE_SIZE,
)
from infra.types import Position, TradingSignal

logger = logging.getLogger(__name__)


def kelly_size(
    bankroll: float,
    edge: float,
    market_price: float,
    fraction: float = KELLY_FRACTION,
    max_pct: float = MAX_POSITION_PCT,
) -> float:
    """Quarter-Kelly position sizing.

    Returns 0.0 for invalid inputs (edge <= 0, price out of (0,1), negative kelly).
    Caps at max_pct * bankroll. Rounds to 2 decimals.
    """
    if edge <= 0 or market_price <= 0 or market_price >= 1 or bankroll <= 0:
        return 0.0

    b = (1 / market_price) - 1          # implied odds
    p = market_price + edge             # estimated true probability
    q = 1 - p

    if b <= 0:
        return 0.0

    kelly_full = (b * p - q) / b

    if kelly_full <= 0:
        return 0.0

    size = bankroll * kelly_full * fraction
    cap = max_pct * bankroll
    return round(min(size, cap), 2)


def check_exposure(
    open_positions: list[Position],
    max_positions: int = MAX_SIMULTANEOUS_POSITIONS,
) -> bool:
    """Return True if fewer than max_positions are open."""
    open_count = sum(1 for p in open_positions if p.status == "open")
    return open_count < max_positions


def check_category_exposure(
    open_positions: list[Position],
    new_category: str,
    max_per_category: int = 2,
) -> bool:
    """Return True if fewer than max_per_category open positions share new_category."""
    count = sum(
        1
        for p in open_positions
        if p.status == "open" and new_category in p.signal.question.lower()
    )
    return count < max_per_category


def check_total_exposure(
    open_positions: list[Position],
    bankroll: float,
    max_exposure_pct: float = 0.40,
) -> bool:
    """Return True if total open exposure < max_exposure_pct * bankroll."""
    total = sum(p.size_usdc for p in open_positions if p.status == "open")
    return total < max_exposure_pct * bankroll


def check_circuit_breaker(
    conn: sqlite3.Connection,
    bankroll: float,
    lookback_days: int = 7,
    max_drawdown: float = 0.20,
) -> bool:
    """Return False if recent losses exceed max_drawdown * bankroll (stop trading).

    Fails open: returns True on DB errors so trading isn't blocked by DB issues.
    """
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0) AS total_pnl
            FROM trades
            WHERE status IN ('won', 'lost')
              AND resolution_date >= date('now', ?)
            """,
            (f"-{lookback_days} days",),
        ).fetchone()
        total_pnl: float = float(row[0]) if row else 0.0
    except sqlite3.Error:
        logger.warning("circuit_breaker_db_error", extra={"action": "fail_open"})
        return True

    if total_pnl < 0 and abs(total_pnl) > max_drawdown * bankroll:
        logger.warning(
            "circuit_breaker_triggered",
            extra={"pnl_7d": total_pnl, "bankroll": bankroll, "threshold": max_drawdown},
        )
        return False

    return True


def compute_position_size(
    signal: TradingSignal,
    bankroll: float,
    open_positions: list[Position],
    conn: sqlite3.Connection,
) -> float:
    """Main entry point — gate checks then Kelly sizing.

    Returns the USDC amount to bet, or 0.0 if any check fails.
    """
    market_id = signal.market_id
    edge = signal.edge_net

    if not check_circuit_breaker(conn, bankroll):
        logger.info("position_sized", extra={
            "market_id": market_id, "edge": edge,
            "size": 0.0, "reason": "circuit_breaker_triggered",
        })
        return 0.0

    if not check_exposure(open_positions):
        logger.info("position_sized", extra={
            "market_id": market_id, "edge": edge,
            "size": 0.0, "reason": "max_positions_reached",
        })
        return 0.0

    if not check_total_exposure(open_positions, bankroll):
        logger.info("position_sized", extra={
            "market_id": market_id, "edge": edge,
            "size": 0.0, "reason": "max_total_exposure",
        })
        return 0.0

    size = kelly_size(bankroll, edge, signal.market_probability)

    if size < MIN_TRADE_SIZE:
        logger.info("position_sized", extra={
            "market_id": market_id, "edge": edge,
            "size": 0.0, "reason": "below_min_trade_size",
        })
        return 0.0

    logger.info("position_sized", extra={
        "market_id": market_id, "edge": edge,
        "size": size, "reason": "ok",
    })
    return size
