"""Position management — portfolio snapshot, resolution tracking, health check."""
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

import requests
from py_clob_client.client import ClobClient

from execution.sizing import check_circuit_breaker, check_total_exposure
from infra.config import MAX_SIMULTANEOUS_POSITIONS
from infra.db import get_open_positions, update_trade_result
from infra.telegram import send_alert
from infra.types import Position, TradingSignal

logger = logging.getLogger(__name__)

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_REQUEST_TIMEOUT = 10


# ── Portfolio snapshot ────────────────────────────────────────────────────────

def get_portfolio_snapshot(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Build a complete view of current portfolio state.

    Returns position count, exposure, categories, and available slots.
    Never crashes — returns empty snapshot on error.
    """
    try:
        raw_positions = get_open_positions()
        positions = _rows_to_positions(raw_positions)
        total_exposure = sum(p.size_usdc for p in positions)
        categories: dict[str, int] = {}
        for p in positions:
            cat = _extract_category(p.signal.question)
            categories[cat] = categories.get(cat, 0) + 1

        count = len(positions)
        snapshot: dict[str, Any] = {
            "open_positions": positions,
            "total_exposure_usdc": round(total_exposure, 2),
            "position_count": count,
            "categories": categories,
            "available_slots": MAX_SIMULTANEOUS_POSITIONS - count,
        }
        logger.info("portfolio_snapshot", extra={
            "positions": count, "exposure": round(total_exposure, 2),
        })
        return snapshot
    except Exception as exc:
        logger.warning("portfolio_snapshot_error", extra={"error": str(exc)})
        return {
            "open_positions": [],
            "total_exposure_usdc": 0.0,
            "position_count": 0,
            "categories": {},
            "available_slots": MAX_SIMULTANEOUS_POSITIONS,
        }


# ── Market resolution ────────────────────────────────────────────────────────

def check_market_resolution(
    client: ClobClient,
    open_positions: list[Position],
) -> list[dict[str, Any]]:
    """Check each open position's market for resolution via Gamma API.

    Returns list of dicts with position, resolved status, and outcome.
    """
    results: list[dict[str, Any]] = []

    for pos in open_positions:
        market_id = pos.signal.market_id
        try:
            resp = requests.get(
                f"{_GAMMA_BASE}/markets/{market_id}",
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            resolved = bool(data.get("closed") or data.get("resolved"))
            outcome: str | None = None
            if resolved:
                outcome = _parse_outcome(data)

            results.append({
                "position": pos,
                "resolved": resolved,
                "outcome": outcome,
                "market_id": market_id,
            })
            logger.info("resolution_check", extra={
                "market_id": market_id, "resolved": resolved,
            })
        except Exception as exc:
            logger.warning("resolution_check_error", extra={
                "market_id": market_id, "error": str(exc),
            })
            results.append({
                "position": pos,
                "resolved": False,
                "outcome": None,
                "market_id": market_id,
            })

    return results


def calculate_pnl(position: Position, outcome: str) -> float:
    """Calculate PnL for a resolved position.

    Win: shares pay $1 each → pnl = size_shares - size_usdc.
    Loss: total loss → pnl = -size_usdc.
    """
    if position.signal.side == outcome:
        pnl = position.size_shares * 1.0 - position.size_usdc
    else:
        pnl = -position.size_usdc
    return round(pnl, 2)


def close_resolved_positions(
    conn: sqlite3.Connection,
    resolved: list[dict[str, Any]],
) -> int:
    """Close resolved positions: update DB + send Telegram alerts.

    Returns count of closed positions.
    """
    closed = 0

    for entry in resolved:
        if not entry.get("resolved") or entry.get("outcome") is None:
            continue

        pos: Position = entry["position"]
        outcome: str = entry["outcome"]
        pnl = calculate_pnl(pos, outcome)
        status = "won" if pnl > 0 else "lost"
        exit_price = 1.0 if status == "won" else 0.0
        trade_id = int(pos.position_id)

        try:
            update_trade_result(
                trade_id=trade_id,
                status=status,
                exit_price=exit_price,
                pnl=pnl,
                resolution_date=datetime.now(UTC).isoformat(),
            )
        except Exception as exc:
            logger.error("close_position_db_error", extra={
                "trade_id": trade_id, "error": str(exc),
            })
            continue

        try:
            icon = "\U0001f7e2" if status == "won" else "\U0001f534"
            sign = "+" if pnl > 0 else ""
            msg = f"{icon} {status.upper()}: {pos.signal.question[:80]} | {sign}${pnl:.2f}"
            send_alert(msg)
        except Exception as exc:
            logger.warning("close_position_telegram_error", extra={
                "trade_id": trade_id, "error": str(exc),
            })

        logger.info("position_closed", extra={
            "trade_id": trade_id, "pnl": pnl, "status": status,
        })
        closed += 1

    return closed


# ── Health check ──────────────────────────────────────────────────────────────

def portfolio_health_check(
    conn: sqlite3.Connection,
    bankroll: float,
) -> dict[str, Any]:
    """Pre-cycle health check: circuit breaker + exposure + 7-day PnL.

    Returns a dict with can_trade flag and diagnostic info.
    """
    try:
        raw_positions = get_open_positions()
        positions = _rows_to_positions(raw_positions)
    except Exception:
        positions = []

    circuit_ok = check_circuit_breaker(conn, bankroll)
    exposure_ok = check_total_exposure(positions, bankroll)
    can_trade = circuit_ok and exposure_ok

    total_exposure = sum(p.size_usdc for p in positions)

    pnl_7d = _get_7d_pnl(conn)
    drawdown_pct = round(abs(pnl_7d) / bankroll, 4) if bankroll > 0 and pnl_7d < 0 else 0.0

    result: dict[str, Any] = {
        "circuit_breaker_ok": circuit_ok,
        "exposure_ok": exposure_ok,
        "can_trade": can_trade,
        "open_positions": len(positions),
        "total_exposure_usdc": round(total_exposure, 2),
        "pnl_7d": round(pnl_7d, 2),
        "drawdown_pct": drawdown_pct,
    }
    logger.info("health_check", extra={
        "can_trade": can_trade, "positions": len(positions),
        "drawdown_pct": drawdown_pct,
    })
    return result


# ── Resolution cycle ──────────────────────────────────────────────────────────

def run_resolution_cycle(
    conn: sqlite3.Connection,
    client: ClobClient,
) -> int:
    """Check all open positions for resolution and close resolved ones.

    Returns count of newly closed positions.
    """
    try:
        raw_positions = get_open_positions()
        positions = _rows_to_positions(raw_positions)
    except Exception as exc:
        logger.warning("resolution_cycle_error", extra={"error": str(exc)})
        return 0

    if not positions:
        return 0

    resolved = check_market_resolution(client, positions)
    resolved_only = [r for r in resolved if r.get("resolved")]

    if not resolved_only:
        return 0

    return close_resolved_positions(conn, resolved_only)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _rows_to_positions(rows: list[dict[str, Any]]) -> list[Position]:
    """Convert DB row dicts to Position objects."""
    positions: list[Position] = []
    for row in rows:
        signal = TradingSignal(
            market_id=row["market_id"],
            question=row["question"],
            side=row["side"],
            agent_probability=row["agent_probability"],
            market_probability=row["market_probability"],
            edge_net=row["edge_net"],
            confidence=row["confidence"],
            tradeable=True,
            news_context="",
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
        positions.append(Position(
            position_id=str(row["id"]),
            signal=signal,
            entry_price=row["entry_price"],
            size_usdc=row["size_usdc"],
            size_shares=row["size_shares"],
            order_id=row["order_id"],
            status=row["status"],
            pnl=row.get("pnl"),
        ))
    return positions


def _extract_category(question: str) -> str:
    """Simple category extraction from question text."""
    q = question.lower()
    for cat in ("politics", "sports", "science", "geopolitics", "crypto", "economy"):
        if cat in q:
            return cat
    return "other"


def _parse_outcome(market_data: dict[str, Any]) -> str | None:
    """Parse resolution outcome from Gamma API market data."""
    outcomes = market_data.get("outcomes")
    resolution = market_data.get("resolution_value")

    if resolution is not None:
        return "YES" if str(resolution) == "1" else "NO"

    if outcomes and isinstance(outcomes, list):
        for o in outcomes:
            if isinstance(o, dict) and o.get("winner"):
                return str(o.get("value", "YES")).upper()

    return None


def _get_7d_pnl(conn: sqlite3.Connection) -> float:
    """Sum PnL from resolved trades in the last 7 days."""
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0)
            FROM trades
            WHERE status IN ('won', 'lost')
              AND resolution_date >= date('now', '-7 days')
            """,
        ).fetchone()
        return float(row[0]) if row else 0.0
    except sqlite3.Error:
        return 0.0
