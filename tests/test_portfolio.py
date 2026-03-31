"""Tests for execution/portfolio.py — position management + resolution tracking."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from execution.portfolio import (
    calculate_pnl,
    check_market_resolution,
    close_resolved_positions,
    get_portfolio_snapshot,
    portfolio_health_check,
    run_resolution_cycle,
)
from infra.types import Position, TradingSignal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signal(
    market_id: str = "mkt-1",
    question: str = "Will X happen?",
    side: str = "YES",
) -> TradingSignal:
    return TradingSignal(
        market_id=market_id,
        question=question,
        side=side,
        agent_probability=0.60,
        market_probability=0.50,
        edge_net=0.08,
        confidence=7,
        tradeable=True,
        news_context="test",
        timestamp=datetime.now(timezone.utc),
    )


def _make_position(
    position_id: str = "1",
    side: str = "YES",
    size_usdc: float = 50.0,
    size_shares: float = 100.0,
    status: str = "open",
    question: str = "Will X happen?",
    market_id: str = "mkt-1",
) -> Position:
    return Position(
        position_id=position_id,
        signal=_make_signal(market_id=market_id, question=question, side=side),
        entry_price=0.50,
        size_usdc=size_usdc,
        size_shares=size_shares,
        order_id="ord-1",
        status=status,
        pnl=None,
    )


def _make_db(trades: list[dict] | None = None) -> sqlite3.Connection:
    """In-memory DB with trades table and optional seed data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            market_id TEXT NOT NULL,
            question TEXT NOT NULL,
            side TEXT NOT NULL,
            size_usdc REAL NOT NULL,
            entry_price REAL NOT NULL,
            agent_probability REAL NOT NULL,
            market_probability REAL NOT NULL,
            edge_net REAL NOT NULL,
            confidence INTEGER NOT NULL,
            order_id TEXT NOT NULL DEFAULT '',
            size_shares REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'open',
            exit_price REAL,
            pnl REAL,
            resolution_date TEXT
        )
    """)
    if trades:
        for t in trades:
            conn.execute(
                """INSERT INTO trades
                    (timestamp, market_id, question, side, size_usdc, entry_price,
                     agent_probability, market_probability, edge_net, confidence, status,
                     pnl, resolution_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    t.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    t.get("market_id", "mkt-1"),
                    t.get("question", "test?"),
                    t.get("side", "YES"),
                    t.get("size_usdc", 50.0),
                    t.get("entry_price", 0.50),
                    t.get("agent_probability", 0.60),
                    t.get("market_probability", 0.50),
                    t.get("edge_net", 0.08),
                    t.get("confidence", 7),
                    t.get("status", "open"),
                    t.get("pnl"),
                    t.get("resolution_date"),
                ),
            )
    conn.commit()
    return conn


# ── calculate_pnl ────────────────────────────────────────────────────────────

def test_calculate_pnl_win() -> None:
    """Side='YES', outcome='YES' → pnl = shares*1 - cost = 100 - 50 = 50."""
    pos = _make_position(side="YES", size_usdc=50.0, size_shares=100.0)
    assert calculate_pnl(pos, "YES") == 50.0


def test_calculate_pnl_loss() -> None:
    """Side='YES', outcome='NO' → pnl = -50."""
    pos = _make_position(side="YES", size_usdc=50.0, size_shares=100.0)
    assert calculate_pnl(pos, "NO") == -50.0


def test_calculate_pnl_no_side_win() -> None:
    """Side='NO', outcome='NO' → positive pnl."""
    pos = _make_position(side="NO", size_usdc=50.0, size_shares=100.0)
    pnl = calculate_pnl(pos, "NO")
    assert pnl > 0


def test_calculate_pnl_no_side_loss() -> None:
    """Side='NO', outcome='YES' → pnl = -size_usdc."""
    pos = _make_position(side="NO", size_usdc=50.0, size_shares=100.0)
    assert calculate_pnl(pos, "YES") == -50.0


# ── get_portfolio_snapshot ────────────────────────────────────────────────────

@patch("execution.portfolio.get_open_positions")
def test_snapshot_with_positions(mock_get: MagicMock) -> None:
    """3 open positions → count=3, exposure=sum of sizes, available_slots=2."""
    mock_get.return_value = [
        {
            "id": i, "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_id": f"mkt-{i}", "question": "Will politics event?",
            "side": "YES", "size_usdc": 50.0, "entry_price": 0.50,
            "agent_probability": 0.60, "market_probability": 0.50,
            "edge_net": 0.08, "confidence": 7, "status": "open",
            "order_id": f"ord-{i}", "size_shares": 100.0,
        }
        for i in range(1, 4)
    ]
    conn = _make_db()
    snap = get_portfolio_snapshot(conn)
    assert snap["position_count"] == 3
    assert snap["total_exposure_usdc"] == 150.0
    assert snap["available_slots"] == 2
    conn.close()


@patch("execution.portfolio.get_open_positions", return_value=[])
def test_snapshot_empty(mock_get: MagicMock) -> None:
    """No positions → count=0, exposure=0."""
    conn = _make_db()
    snap = get_portfolio_snapshot(conn)
    assert snap["position_count"] == 0
    assert snap["total_exposure_usdc"] == 0.0
    assert snap["available_slots"] == 5
    conn.close()


@patch("execution.portfolio.get_open_positions", side_effect=Exception("DB error"))
def test_snapshot_db_error(mock_get: MagicMock) -> None:
    """DB throws → returns empty snapshot."""
    conn = _make_db()
    snap = get_portfolio_snapshot(conn)
    assert snap["position_count"] == 0
    conn.close()


# ── check_market_resolution ──────────────────────────────────────────────────

@patch("execution.portfolio.requests.get")
def test_resolution_market_resolved(mock_get: MagicMock) -> None:
    """Gamma API returns resolved market → resolved=True, outcome='YES'."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"closed": True, "resolved": True, "resolution_value": "1"}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    pos = _make_position()
    client = MagicMock()
    results = check_market_resolution(client, [pos])
    assert len(results) == 1
    assert results[0]["resolved"] is True
    assert results[0]["outcome"] == "YES"


@patch("execution.portfolio.requests.get")
def test_resolution_market_still_open(mock_get: MagicMock) -> None:
    """Active market → resolved=False."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"closed": False, "resolved": False}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    pos = _make_position()
    client = MagicMock()
    results = check_market_resolution(client, [pos])
    assert results[0]["resolved"] is False
    assert results[0]["outcome"] is None


@patch("execution.portfolio.requests.get")
def test_resolution_api_error_one_market(mock_get: MagicMock) -> None:
    """One API fails → that one resolved=False, other still checked."""
    mock_ok = MagicMock()
    mock_ok.json.return_value = {"closed": True, "resolution_value": "1"}
    mock_ok.raise_for_status.return_value = None

    mock_get.side_effect = [Exception("timeout"), mock_ok]

    pos1 = _make_position(position_id="1", market_id="mkt-1")
    pos2 = _make_position(position_id="2", market_id="mkt-2")
    client = MagicMock()

    results = check_market_resolution(client, [pos1, pos2])
    assert results[0]["resolved"] is False
    assert results[1]["resolved"] is True


# ── close_resolved_positions ──────────────────────────────────────────────────

@patch("execution.portfolio.send_alert")
@patch("execution.portfolio.update_trade_result")
def test_close_winning_position(mock_update: MagicMock, mock_alert: MagicMock) -> None:
    """Won position → DB updated with positive pnl."""
    pos = _make_position(position_id="1", side="YES", size_usdc=50.0, size_shares=100.0)
    resolved = [{"position": pos, "resolved": True, "outcome": "YES", "market_id": "mkt-1"}]
    conn = _make_db()
    count = close_resolved_positions(conn, resolved)
    assert count == 1
    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args
    assert call_kwargs[1]["status"] == "won" or call_kwargs[0][1] == "won"
    conn.close()


@patch("execution.portfolio.send_alert")
@patch("execution.portfolio.update_trade_result")
def test_close_losing_position(mock_update: MagicMock, mock_alert: MagicMock) -> None:
    """Lost position → DB updated with negative pnl."""
    pos = _make_position(position_id="1", side="YES", size_usdc=50.0, size_shares=100.0)
    resolved = [{"position": pos, "resolved": True, "outcome": "NO", "market_id": "mkt-1"}]
    conn = _make_db()
    count = close_resolved_positions(conn, resolved)
    assert count == 1
    mock_update.assert_called_once()
    conn.close()


@patch("execution.portfolio.send_alert")
@patch("execution.portfolio.update_trade_result")
def test_close_multiple_positions(mock_update: MagicMock, mock_alert: MagicMock) -> None:
    """2 resolved (1 won, 1 lost) → returns 2."""
    pos_win = _make_position(position_id="1", side="YES", size_usdc=50.0, size_shares=100.0)
    pos_lose = _make_position(position_id="2", side="YES", size_usdc=50.0, size_shares=100.0)
    resolved = [
        {"position": pos_win, "resolved": True, "outcome": "YES", "market_id": "mkt-1"},
        {"position": pos_lose, "resolved": True, "outcome": "NO", "market_id": "mkt-2"},
    ]
    conn = _make_db()
    count = close_resolved_positions(conn, resolved)
    assert count == 2
    conn.close()


@patch("execution.portfolio.send_alert")
@patch("execution.portfolio.update_trade_result")
def test_close_skips_unresolved(mock_update: MagicMock, mock_alert: MagicMock) -> None:
    """Mix of resolved and unresolved → only closes resolved."""
    pos1 = _make_position(position_id="1", side="YES")
    pos2 = _make_position(position_id="2", side="YES")
    entries = [
        {"position": pos1, "resolved": True, "outcome": "YES", "market_id": "mkt-1"},
        {"position": pos2, "resolved": False, "outcome": None, "market_id": "mkt-2"},
    ]
    conn = _make_db()
    count = close_resolved_positions(conn, entries)
    assert count == 1
    conn.close()


# ── portfolio_health_check ────────────────────────────────────────────────────

@patch("execution.portfolio.get_open_positions", return_value=[])
@patch("execution.portfolio.check_circuit_breaker", return_value=True)
@patch("execution.portfolio.check_total_exposure", return_value=True)
def test_health_check_all_good(
    mock_exp: MagicMock, mock_cb: MagicMock, mock_pos: MagicMock,
) -> None:
    """No breaker, low exposure → can_trade=True."""
    conn = _make_db()
    result = portfolio_health_check(conn, bankroll=1000)
    assert result["can_trade"] is True
    assert result["circuit_breaker_ok"] is True
    assert result["exposure_ok"] is True
    conn.close()


@patch("execution.portfolio.get_open_positions", return_value=[])
@patch("execution.portfolio.check_circuit_breaker", return_value=False)
@patch("execution.portfolio.check_total_exposure", return_value=True)
def test_health_check_breaker_triggered(
    mock_exp: MagicMock, mock_cb: MagicMock, mock_pos: MagicMock,
) -> None:
    """-25% drawdown → can_trade=False."""
    conn = _make_db()
    result = portfolio_health_check(conn, bankroll=1000)
    assert result["can_trade"] is False
    assert result["circuit_breaker_ok"] is False
    conn.close()


@patch("execution.portfolio.get_open_positions", return_value=[])
@patch("execution.portfolio.check_circuit_breaker", return_value=True)
@patch("execution.portfolio.check_total_exposure", return_value=False)
def test_health_check_exposure_maxed(
    mock_exp: MagicMock, mock_cb: MagicMock, mock_pos: MagicMock,
) -> None:
    """Max exposure → can_trade=False."""
    conn = _make_db()
    result = portfolio_health_check(conn, bankroll=1000)
    assert result["can_trade"] is False
    assert result["exposure_ok"] is False
    conn.close()


# ── run_resolution_cycle ──────────────────────────────────────────────────────

@patch("execution.portfolio.get_open_positions", return_value=[])
def test_resolution_cycle_no_positions(mock_pos: MagicMock) -> None:
    """No open positions → returns 0."""
    conn = _make_db()
    client = MagicMock()
    assert run_resolution_cycle(conn, client) == 0
    conn.close()


@patch("execution.portfolio.close_resolved_positions", return_value=1)
@patch("execution.portfolio.check_market_resolution")
@patch("execution.portfolio.get_open_positions")
def test_resolution_cycle_closes_resolved(
    mock_pos: MagicMock, mock_check: MagicMock, mock_close: MagicMock,
) -> None:
    """2 open, 1 resolved → returns 1."""
    mock_pos.return_value = [
        {
            "id": i, "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_id": f"mkt-{i}", "question": "test?", "side": "YES",
            "size_usdc": 50.0, "entry_price": 0.50, "agent_probability": 0.60,
            "market_probability": 0.50, "edge_net": 0.08, "confidence": 7,
            "status": "open", "order_id": f"ord-{i}", "size_shares": 100.0,
        }
        for i in range(1, 3)
    ]
    pos1 = _make_position(position_id="1")
    pos2 = _make_position(position_id="2")
    mock_check.return_value = [
        {"position": pos1, "resolved": True, "outcome": "YES", "market_id": "mkt-1"},
        {"position": pos2, "resolved": False, "outcome": None, "market_id": "mkt-2"},
    ]

    conn = _make_db()
    client = MagicMock()
    count = run_resolution_cycle(conn, client)
    assert count == 1
    conn.close()
