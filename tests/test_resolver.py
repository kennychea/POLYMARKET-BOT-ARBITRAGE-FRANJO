"""Tests for core.resolver — standalone market resolution checker."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from core.resolver import (
    calculate_pnl,
    cleanup_duplicate_trades,
    fetch_market_resolution,
    parse_resolution,
    resolve_open_trades,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def _mock_db(tmp_path, monkeypatch):
    """Set up an in-memory-style temp DB with one open trade."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("infra.config.DB_PATH", db_path)

    from infra.db import init_db

    init_db()

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO trades
            (timestamp, market_id, question, side, size_usdc, entry_price,
             agent_probability, market_probability, edge_net, confidence,
             order_id, size_shares, status)
        VALUES
            ('2026-03-31T21:00:00', '0xABC', 'Will X happen?', 'YES', 0.0, 0.30,
             0.45, 0.30, 0.10, 7, '', 0.0, 'open'),
            ('2026-03-31T21:01:00', '0xDEF', 'Will Y happen?', 'NO', 10.0, 0.60,
             0.35, 0.60, 0.08, 6, 'order-1', 16.67, 'open')
        """,
    )
    conn.commit()
    conn.close()
    return db_path


# ── parse_resolution ─────────────────────────────────────────────────────────

class TestParseResolution:
    def test_not_resolved_open(self):
        data = {"closed": False, "active": True, "tokens": [
            {"outcome": "Yes", "winner": False},
            {"outcome": "No", "winner": False},
        ]}
        is_resolved, outcome = parse_resolution(data)
        assert is_resolved is False
        assert outcome is None

    def test_resolved_yes_wins(self):
        data = {"closed": True, "active": False, "tokens": [
            {"outcome": "Yes", "winner": True},
            {"outcome": "No", "winner": False},
        ]}
        is_resolved, outcome = parse_resolution(data)
        assert is_resolved is True
        assert outcome == "YES"

    def test_resolved_no_wins(self):
        data = {"closed": True, "active": False, "tokens": [
            {"outcome": "Yes", "winner": False},
            {"outcome": "No", "winner": True},
        ]}
        is_resolved, outcome = parse_resolution(data)
        assert is_resolved is True
        assert outcome == "NO"

    def test_closed_but_no_winner_yet(self):
        """Market closed (halted/UMA pending) but no winner → not resolved."""
        data = {"closed": True, "active": False, "tokens": [
            {"outcome": "Yes", "winner": False},
            {"outcome": "No", "winner": False},
        ]}
        is_resolved, outcome = parse_resolution(data)
        assert is_resolved is False
        assert outcome is None

    def test_closed_no_tokens(self):
        """Edge case: closed with no tokens data → not resolved."""
        data = {"closed": True}
        is_resolved, outcome = parse_resolution(data)
        assert is_resolved is False
        assert outcome is None


# ── calculate_pnl ────────────────────────────────────────────────────────────

class TestCalculatePnl:
    def test_won_with_shares(self):
        """Real trade: bought 16.67 shares at $10 → win = 16.67 - 10 = $6.67."""
        status, exit_price, pnl = calculate_pnl(
            side="YES", outcome="YES", size_usdc=10.0, size_shares=16.67, entry_price=0.60,
        )
        assert status == "won"
        assert exit_price == 1.0
        assert pnl == 6.67

    def test_lost_with_shares(self):
        """Real trade: lost $10."""
        status, exit_price, pnl = calculate_pnl(
            side="YES", outcome="NO", size_usdc=10.0, size_shares=16.67, entry_price=0.60,
        )
        assert status == "lost"
        assert exit_price == 0.0
        assert pnl == -10.0

    def test_won_paper_trade(self):
        """Paper trade (size_usdc=0): notional PnL based on entry_price."""
        status, exit_price, pnl = calculate_pnl(
            side="YES", outcome="YES", size_usdc=0.0, size_shares=0.0, entry_price=0.30,
        )
        assert status == "won"
        assert exit_price == 1.0
        assert pnl == 2.33  # (1.0 - 0.30) / 0.30 * 1.0

    def test_lost_paper_trade(self):
        """Paper trade loss: notional $1."""
        status, exit_price, pnl = calculate_pnl(
            side="NO", outcome="YES", size_usdc=0.0, size_shares=0.0, entry_price=0.70,
        )
        assert status == "lost"
        assert exit_price == 0.0
        assert pnl == -1.0

    def test_no_side_won(self):
        """NO side wins when outcome is NO."""
        status, exit_price, pnl = calculate_pnl(
            side="NO", outcome="NO", size_usdc=5.0, size_shares=10.0, entry_price=0.50,
        )
        assert status == "won"
        assert exit_price == 1.0
        assert pnl == 5.0  # 10 shares * $1 - $5


# ── resolve_open_trades (integration with mock DB + mock API) ────────────────

@pytest.mark.usefixtures("_mock_db")
class TestResolveOpenTrades:
    def _clob_response(self, resolved: bool, winning_outcome: str = "Yes"):
        """Build a fake CLOB API response."""
        if resolved:
            tokens = [
                {"outcome": "Yes", "winner": winning_outcome == "Yes"},
                {"outcome": "No", "winner": winning_outcome == "No"},
            ]
        else:
            tokens = [
                {"outcome": "Yes", "winner": False},
                {"outcome": "No", "winner": False},
            ]
        return {
            "closed": resolved,
            "active": not resolved,
            "accepting_orders": not resolved,
            "tokens": tokens,
        }

    @patch("core.resolver.fetch_market_resolution")
    def test_resolve_won_trade(self, mock_fetch, _mock_db):
        """Market resolved YES, trade side=YES → won."""
        mock_fetch.return_value = self._clob_response(True, "Yes")

        summary = resolve_open_trades(dry_run=False)

        assert summary["resolved"] == 2
        assert summary["won"] >= 1

        # Verify DB was updated
        conn = sqlite3.connect(_mock_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE status = 'won'").fetchall()
        assert len(rows) >= 1
        won_trade = dict(rows[0])
        assert won_trade["exit_price"] == 1.0
        assert won_trade["pnl"] is not None
        assert won_trade["resolution_date"] is not None
        conn.close()

    @patch("core.resolver.fetch_market_resolution")
    def test_resolve_lost_trade(self, mock_fetch, _mock_db):
        """Market resolved NO, trade side=YES → lost."""
        mock_fetch.return_value = self._clob_response(True, "No")

        summary = resolve_open_trades(dry_run=False)

        conn = sqlite3.connect(_mock_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE status = 'lost'").fetchall()
        assert len(rows) >= 1
        lost_trade = dict(rows[0])
        assert lost_trade["exit_price"] == 0.0
        assert lost_trade["pnl"] is not None
        conn.close()

    @patch("core.resolver.fetch_market_resolution")
    def test_resolve_not_yet_resolved(self, mock_fetch, _mock_db):
        """Market not yet resolved → all trades remain open."""
        mock_fetch.return_value = self._clob_response(False)

        summary = resolve_open_trades(dry_run=False)

        assert summary["resolved"] == 0
        assert summary["skipped"] == 2

        conn = sqlite3.connect(_mock_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE status = 'open'").fetchall()
        assert len(rows) == 2
        conn.close()

    @patch("core.resolver.fetch_market_resolution")
    def test_resolve_pnl_calculation(self, mock_fetch, _mock_db):
        """Verify PnL is correctly calculated and stored."""
        # Market resolves YES — trade #1 (YES side) wins, trade #2 (NO side) loses
        mock_fetch.return_value = self._clob_response(True, "Yes")

        summary = resolve_open_trades(dry_run=False)

        assert summary["resolved"] == 2
        assert summary["won"] == 1   # trade #1: YES side, YES outcome
        assert summary["lost"] == 1  # trade #2: NO side, YES outcome

        conn = sqlite3.connect(_mock_db)
        conn.row_factory = sqlite3.Row

        won = dict(conn.execute("SELECT * FROM trades WHERE id = 1").fetchone())
        assert won["status"] == "won"
        assert won["pnl"] > 0

        lost = dict(conn.execute("SELECT * FROM trades WHERE id = 2").fetchone())
        assert lost["status"] == "lost"
        assert lost["pnl"] < 0
        assert lost["pnl"] == -10.0  # size_usdc = 10.0
        conn.close()

    @patch("core.resolver.fetch_market_resolution")
    def test_resolve_dry_run_no_db_write(self, mock_fetch, _mock_db):
        """Dry-run mode should NOT modify the DB."""
        mock_fetch.return_value = self._clob_response(True, "Yes")

        summary = resolve_open_trades(dry_run=True)

        assert summary["resolved"] == 2
        assert summary["dry_run"] is True

        # DB should still have all trades as 'open'
        conn = sqlite3.connect(_mock_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trades WHERE status = 'open'").fetchall()
        assert len(rows) == 2
        conn.close()

    @patch("core.resolver.fetch_market_resolution")
    def test_resolve_summary_output(self, mock_fetch, _mock_db):
        """Summary dict has correct structure and counts."""
        mock_fetch.return_value = self._clob_response(True, "Yes")

        summary = resolve_open_trades(dry_run=False)

        assert "total_open" in summary
        assert "resolved" in summary
        assert "won" in summary
        assert "lost" in summary
        assert "skipped" in summary
        assert "errors" in summary
        assert "total_pnl" in summary
        assert "dry_run" in summary
        assert "details" in summary
        assert summary["total_open"] == 2
        assert summary["resolved"] == summary["won"] + summary["lost"]
        assert isinstance(summary["details"], list)
        assert len(summary["details"]) == summary["resolved"]

    @patch("core.resolver.fetch_market_resolution")
    def test_resolve_api_error_continues(self, mock_fetch, _mock_db):
        """API error on one trade doesn't stop resolution of others."""
        mock_fetch.side_effect = [
            Exception("Connection timeout"),
            self._clob_response(True, "Yes"),
        ]

        summary = resolve_open_trades(dry_run=False)

        assert summary["errors"] == 1
        assert summary["resolved"] == 1


# ── cleanup_duplicate_trades ─────────────────────────────────────────────────


@pytest.fixture()
def _dupes_db(tmp_path, monkeypatch):
    """DB with duplicate trades for cleanup tests."""
    db_path = str(tmp_path / "dupes.db")
    monkeypatch.setattr("infra.config.DB_PATH", db_path)

    from infra.db import init_db

    init_db()

    conn = sqlite3.connect(db_path)
    # 3 trades on same market+side — ids 1, 2, 3
    for i, ts in enumerate(["2026-03-31T20:00:00", "2026-03-31T21:00:00", "2026-03-31T22:00:00"]):
        conn.execute(
            """
            INSERT INTO trades
                (timestamp, market_id, question, side, size_usdc, entry_price,
                 agent_probability, market_probability, edge_net, confidence, status)
            VALUES (?, '0xAAA', 'Will X?', 'YES', 0.0, 0.30, 0.45, 0.30, 0.10, 7, 'open')
            """,
            (ts,),
        )
    # 1 trade on different side of same market — id 4
    conn.execute(
        """
        INSERT INTO trades
            (timestamp, market_id, question, side, size_usdc, entry_price,
             agent_probability, market_probability, edge_net, confidence, status)
        VALUES ('2026-03-31T20:30:00', '0xAAA', 'Will X?', 'NO', 0.0, 0.70, 0.55, 0.70, 0.08, 6, 'open')
        """
    )
    # 1 unique trade on different market — id 5
    conn.execute(
        """
        INSERT INTO trades
            (timestamp, market_id, question, side, size_usdc, entry_price,
             agent_probability, market_probability, edge_net, confidence, status)
        VALUES ('2026-03-31T20:00:00', '0xBBB', 'Will Y?', 'YES', 0.0, 0.50, 0.60, 0.50, 0.05, 7, 'open')
        """
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.usefixtures("_dupes_db")
class TestCleanupDupes:
    def test_cleanup_dupes_keeps_first(self, _dupes_db):
        """3 trades same market+side → keep oldest (id=1), delete 2."""
        result = cleanup_duplicate_trades(dry_run=False)
        assert result["removed"] == 2

        conn = sqlite3.connect(_dupes_db)
        rows = conn.execute(
            "SELECT id FROM trades WHERE market_id = '0xAAA' AND side = 'YES' ORDER BY id"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1  # kept the first
        conn.close()

    def test_cleanup_dupes_different_sides_kept(self, _dupes_db):
        """Same market, YES and NO → both kept (different sides)."""
        cleanup_duplicate_trades(dry_run=False)

        conn = sqlite3.connect(_dupes_db)
        rows = conn.execute(
            "SELECT DISTINCT side FROM trades WHERE market_id = '0xAAA'"
        ).fetchall()
        sides = {r[0] for r in rows}
        assert sides == {"YES", "NO"}
        conn.close()

    def test_cleanup_dupes_dry_run(self, _dupes_db):
        """Dry-run should not delete anything."""
        result = cleanup_duplicate_trades(dry_run=True)
        assert result["removed"] == 2  # would remove 2

        conn = sqlite3.connect(_dupes_db)
        total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        assert total == 5  # all 5 still there
        conn.close()
