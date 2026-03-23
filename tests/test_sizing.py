"""Tests for execution/sizing.py — Kelly fractional + exposure + circuit breaker."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from execution.sizing import (
    check_category_exposure,
    check_circuit_breaker,
    check_exposure,
    check_total_exposure,
    compute_position_size,
    kelly_size,
)
from infra.config import MAX_POSITION_PCT, MIN_TRADE_SIZE
from infra.types import Position, TradingSignal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signal(
    edge_net: float = 0.08,
    market_probability: float = 0.50,
    market_id: str = "test-market",
    question: str = "Will X happen?",
) -> TradingSignal:
    return TradingSignal(
        market_id=market_id,
        question=question,
        side="YES",
        agent_probability=market_probability + edge_net,
        market_probability=market_probability,
        edge_net=edge_net,
        confidence=7,
        tradeable=True,
        news_context="test context",
        timestamp=datetime.now(timezone.utc),
    )


def _make_position(
    status: str = "open",
    size_usdc: float = 50.0,
    question: str = "Will politics event happen?",
) -> Position:
    return Position(
        position_id="pos-1",
        signal=_make_signal(question=question),
        entry_price=0.50,
        size_usdc=size_usdc,
        size_shares=100.0,
        order_id="ord-1",
        status=status,
        pnl=None,
    )


def _make_db(trades: list[tuple[float, str]] | None = None) -> sqlite3.Connection:
    """Create in-memory DB with trades table and optional resolved trades.

    trades: list of (pnl, resolution_date) tuples.
    """
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
            status              TEXT NOT NULL DEFAULT 'open',
            exit_price          REAL,
            pnl                 REAL,
            resolution_date     TEXT
        )
    """)
    if trades:
        for pnl, res_date in trades:
            status = "won" if pnl >= 0 else "lost"
            conn.execute(
                """
                INSERT INTO trades
                    (timestamp, market_id, question, side, size_usdc, entry_price,
                     agent_probability, market_probability, edge_net, confidence,
                     status, pnl, resolution_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    "mkt-1", "test?", "YES", 50.0, 0.50,
                    0.58, 0.50, 0.06, 7,
                    status, pnl, res_date,
                ),
            )
    conn.commit()
    return conn


# ── Kelly math ────────────────────────────────────────────────────────────────

def test_kelly_size_positive_edge_returns_positive() -> None:
    """edge=0.08, market_price=0.50, bankroll=1000 → size > 0."""
    size = kelly_size(bankroll=1000, edge=0.08, market_price=0.50)
    assert size > 0


def test_kelly_size_negative_edge_returns_zero() -> None:
    """edge=-0.05 → 0.0."""
    assert kelly_size(bankroll=1000, edge=-0.05, market_price=0.50) == 0.0


def test_kelly_size_zero_edge_returns_zero() -> None:
    """edge=0.0 → 0.0."""
    assert kelly_size(bankroll=1000, edge=0.0, market_price=0.50) == 0.0


def test_kelly_size_never_exceeds_max_pct() -> None:
    """Even with huge edge, size <= MAX_POSITION_PCT * bankroll."""
    size = kelly_size(bankroll=1000, edge=0.40, market_price=0.50)
    assert size <= MAX_POSITION_PCT * 1000


def test_kelly_size_quarter_vs_full() -> None:
    """fraction=1.0 gives 4x the size of fraction=0.25 (before cap)."""
    # Use small edge so neither hits the max_pct cap
    quarter = kelly_size(bankroll=1000, edge=0.03, market_price=0.50, fraction=0.25)
    full = kelly_size(bankroll=1000, edge=0.03, market_price=0.50, fraction=1.0)
    assert full == pytest.approx(quarter * 4, rel=0.01)


def test_kelly_size_invalid_market_price_returns_zero() -> None:
    """market_price=0.0 or 1.0 or negative → 0.0."""
    assert kelly_size(bankroll=1000, edge=0.08, market_price=0.0) == 0.0
    assert kelly_size(bankroll=1000, edge=0.08, market_price=1.0) == 0.0
    assert kelly_size(bankroll=1000, edge=0.08, market_price=-0.5) == 0.0


# ── Exposure checks ──────────────────────────────────────────────────────────

def test_check_exposure_under_limit() -> None:
    """4 open positions, max 5 → True."""
    positions = [_make_position() for _ in range(4)]
    assert check_exposure(positions, max_positions=5) is True


def test_check_exposure_at_limit() -> None:
    """5 open positions, max 5 → False."""
    positions = [_make_position() for _ in range(5)]
    assert check_exposure(positions, max_positions=5) is False


def test_check_total_exposure_under() -> None:
    """$350 exposed on $1000 bankroll (35%) → True."""
    positions = [_make_position(size_usdc=70.0) for _ in range(5)]
    assert check_total_exposure(positions, bankroll=1000, max_exposure_pct=0.40) is True


def test_check_total_exposure_over() -> None:
    """$450 exposed on $1000 bankroll (45%) → False."""
    positions = [_make_position(size_usdc=90.0) for _ in range(5)]
    assert check_total_exposure(positions, bankroll=1000, max_exposure_pct=0.40) is False


def test_check_category_exposure_under() -> None:
    """1 position in 'politics', adding another → True."""
    positions = [_make_position(question="Will politics event happen?")]
    assert check_category_exposure(positions, "politics", max_per_category=2) is True


def test_check_category_exposure_at_limit() -> None:
    """2 positions in 'politics', adding third → False."""
    positions = [
        _make_position(question="Will politics event A happen?"),
        _make_position(question="Will politics event B happen?"),
    ]
    assert check_category_exposure(positions, "politics", max_per_category=2) is False


# ── Circuit breaker ───────────────────────────────────────────────────────────

def test_circuit_breaker_safe() -> None:
    """-$100 loss on $1000 bankroll (10%) → True (safe)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = _make_db(trades=[(-100.0, today)])
    assert check_circuit_breaker(conn, bankroll=1000) is True
    conn.close()


def test_circuit_breaker_triggered() -> None:
    """-$250 loss on $1000 bankroll (25%) → False (stop)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = _make_db(trades=[(-250.0, today)])
    assert check_circuit_breaker(conn, bankroll=1000) is False
    conn.close()


# ── Main function ─────────────────────────────────────────────────────────────

def test_compute_position_size_happy_path() -> None:
    """Valid signal, all checks pass → size > 0."""
    conn = _make_db()
    signal = _make_signal(edge_net=0.08, market_probability=0.50)
    size = compute_position_size(signal, bankroll=1000, open_positions=[], conn=conn)
    assert size > 0
    assert size >= MIN_TRADE_SIZE
    conn.close()


def test_compute_position_size_blocked_by_breaker() -> None:
    """Circuit breaker triggered → 0.0."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = _make_db(trades=[(-250.0, today)])
    signal = _make_signal(edge_net=0.08, market_probability=0.50)
    size = compute_position_size(signal, bankroll=1000, open_positions=[], conn=conn)
    assert size == 0.0
    conn.close()


def test_compute_position_size_below_min_trade() -> None:
    """Tiny edge → kelly returns < MIN_TRADE_SIZE → 0.0."""
    conn = _make_db()
    signal = _make_signal(edge_net=0.001, market_probability=0.50)
    size = compute_position_size(signal, bankroll=100, open_positions=[], conn=conn)
    assert size == 0.0
    conn.close()
