"""Tests for paper bankroll tracking — db helpers, kelly sizing, resolver integration."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

import infra.config as cfg


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def _paper_db(tmp_path, monkeypatch):
    """Set up a temp DB with paper_bankroll table and sample trades."""
    db_path = str(tmp_path / "paper.db")
    monkeypatch.setattr("infra.config.DB_PATH", db_path)
    monkeypatch.setattr("infra.config.PAPER_INITIAL_BANKROLL", 500.0)

    from infra.db import init_db

    init_db()
    return db_path


@pytest.fixture()
def _paper_db_with_trades(_paper_db):
    """DB with two open paper trades (kelly-sized)."""
    conn = sqlite3.connect(_paper_db)
    conn.execute(
        """
        INSERT INTO trades
            (timestamp, market_id, question, side, size_usdc, entry_price,
             agent_probability, market_probability, edge_net, confidence,
             order_id, size_shares, status)
        VALUES
            ('2026-03-31T21:00:00', '0xABC', 'Will X happen?', 'YES', 25.0, 0.40,
             0.55, 0.40, 0.10, 7, '', 62.5, 'open'),
            ('2026-03-31T21:01:00', '0xDEF', 'Will Y happen?', 'NO', 15.0, 0.60,
             0.35, 0.60, 0.08, 6, '', 25.0, 'open')
        """,
    )
    # Bankroll after two trades: 500 - 25 - 15 = 460
    conn.execute(
        """
        INSERT INTO paper_bankroll (timestamp, bankroll, trade_id, pnl_delta)
        VALUES
            ('2026-03-31T21:00:00', 475.0, 1, -25.0),
            ('2026-03-31T21:01:00', 460.0, 2, -15.0)
        """,
    )
    conn.commit()
    conn.close()
    return _paper_db


# ── DB helpers ───────────────────────────────────────────────────────────────


class TestPaperBankrollDB:
    def test_get_bankroll_default(self, _paper_db):
        """No bankroll entries → returns PAPER_INITIAL_BANKROLL."""
        from infra.db import get_paper_bankroll

        assert get_paper_bankroll() == 500.0

    def test_get_bankroll_after_trades(self, _paper_db_with_trades):
        """Returns latest bankroll value."""
        from infra.db import get_paper_bankroll

        assert get_paper_bankroll() == 460.0

    def test_update_bankroll(self, _paper_db):
        """update_paper_bankroll inserts a new record."""
        from infra.db import get_paper_bankroll, update_paper_bankroll

        update_paper_bankroll(trade_id=1, pnl_delta=-20.0, new_bankroll=480.0)
        assert get_paper_bankroll() == 480.0

    def test_bankroll_history(self, _paper_db_with_trades):
        """History returns entries newest first."""
        from infra.db import get_paper_bankroll_history

        history = get_paper_bankroll_history()
        assert len(history) == 2
        assert history[0]["bankroll"] == 460.0
        assert history[1]["bankroll"] == 475.0


# ── Kelly sizing ─────────────────────────────────────────────────────────────


class TestPaperKellySize:
    def test_basic_kelly(self, _paper_db):
        """Kelly returns a sensible size for good edge."""
        from infra.db import paper_kelly_size

        size = paper_kelly_size(bankroll=500.0, edge=0.10, market_price=0.50)
        assert size >= cfg.MIN_TRADE_SIZE
        assert size <= 500.0 * 0.10  # max_pct cap

    def test_kelly_zero_edge(self, _paper_db):
        """Zero or negative edge → 0.0."""
        from infra.db import paper_kelly_size

        assert paper_kelly_size(bankroll=500.0, edge=0.0, market_price=0.50) == 0.0
        assert paper_kelly_size(bankroll=500.0, edge=-0.05, market_price=0.50) == 0.0

    def test_kelly_zero_bankroll(self, _paper_db):
        """Zero bankroll → 0.0."""
        from infra.db import paper_kelly_size

        assert paper_kelly_size(bankroll=0.0, edge=0.10, market_price=0.50) == 0.0

    def test_kelly_extreme_price(self, _paper_db):
        """Price at 0 or 1 → 0.0."""
        from infra.db import paper_kelly_size

        assert paper_kelly_size(bankroll=500.0, edge=0.10, market_price=0.0) == 0.0
        assert paper_kelly_size(bankroll=500.0, edge=0.10, market_price=1.0) == 0.0

    def test_kelly_respects_max_pct(self, _paper_db):
        """Size is capped at max_pct * bankroll."""
        from infra.db import paper_kelly_size

        size = paper_kelly_size(bankroll=500.0, edge=0.50, market_price=0.30, max_pct=0.05)
        assert size <= 500.0 * 0.05

    def test_kelly_below_min_trade_returns_zero(self, _paper_db):
        """If computed size < MIN_TRADE_SIZE → 0.0."""
        from infra.db import paper_kelly_size

        # Tiny bankroll → tiny kelly → below MIN_TRADE_SIZE
        size = paper_kelly_size(bankroll=10.0, edge=0.05, market_price=0.50, fraction=0.01)
        assert size == 0.0


# ── Resolver bankroll integration ────────────────────────────────────────────


class TestResolverBankroll:
    @patch("core.resolver.fetch_market_resolution")
    @patch("core.resolver.tg.send_alert")
    def test_resolution_updates_bankroll_on_win(self, mock_tg, mock_fetch, _paper_db_with_trades):
        """Won trade: bankroll increases by size_usdc + pnl."""
        from core.resolver import resolve_open_trades

        mock_fetch.return_value = {
            "closed": True,
            "tokens": [
                {"outcome": "Yes", "winner": True},
                {"outcome": "No", "winner": False},
            ],
        }

        resolve_open_trades(dry_run=False)

        from infra.db import get_paper_bankroll

        bankroll = get_paper_bankroll()
        # Trade 1 (YES, won): pnl = 62.5 * 1.0 - 25.0 = 37.5
        #   bankroll after: 460 + 25.0 + 37.5 = 522.5
        # Trade 2 (NO, lost): pnl = -15.0
        #   bankroll after: 522.5 + 15.0 + (-15.0) = 522.5
        assert bankroll == 522.5

    @patch("core.resolver.fetch_market_resolution")
    @patch("core.resolver.tg.send_alert")
    def test_resolution_sends_telegram(self, mock_tg, mock_fetch, _paper_db_with_trades):
        """Resolved trades trigger Telegram alerts with bankroll info."""
        from core.resolver import resolve_open_trades

        mock_fetch.return_value = {
            "closed": True,
            "tokens": [
                {"outcome": "Yes", "winner": True},
                {"outcome": "No", "winner": False},
            ],
        }

        resolve_open_trades(dry_run=False)

        # Two resolution alerts sent
        assert mock_tg.call_count == 2
        first_call = mock_tg.call_args_list[0][0][0]
        assert "[PAPER]" in first_call
        assert "Resolved" in first_call
        assert "Bankroll" in first_call

    @patch("core.resolver.fetch_market_resolution")
    @patch("core.resolver.tg.send_alert")
    def test_dry_run_no_bankroll_update(self, mock_tg, mock_fetch, _paper_db_with_trades):
        """Dry-run: bankroll is NOT updated."""
        from core.resolver import resolve_open_trades
        from infra.db import get_paper_bankroll

        mock_fetch.return_value = {
            "closed": True,
            "tokens": [
                {"outcome": "Yes", "winner": True},
                {"outcome": "No", "winner": False},
            ],
        }

        resolve_open_trades(dry_run=True)

        assert get_paper_bankroll() == 460.0  # unchanged
        mock_tg.assert_not_called()


# ── calculate_pnl with real paper sizes ─────────────────────────────────────


class TestCalculatePnlPaperSized:
    def test_won_with_paper_shares(self):
        """Paper trade with real sizing: won → shares * 1.0 - size_usdc."""
        from core.resolver import calculate_pnl

        status, exit_price, pnl = calculate_pnl(
            side="YES", outcome="YES", size_usdc=25.0, size_shares=62.5, entry_price=0.40,
        )
        assert status == "won"
        assert pnl == 37.5  # 62.5 - 25.0

    def test_lost_with_paper_shares(self):
        """Paper trade with real sizing: lost → -size_usdc."""
        from core.resolver import calculate_pnl

        status, exit_price, pnl = calculate_pnl(
            side="YES", outcome="NO", size_usdc=25.0, size_shares=62.5, entry_price=0.40,
        )
        assert status == "lost"
        assert pnl == -25.0

    def test_legacy_paper_trade_still_works(self):
        """Legacy paper trade (size_usdc=0): still computes notional PnL."""
        from core.resolver import calculate_pnl

        status, exit_price, pnl = calculate_pnl(
            side="YES", outcome="YES", size_usdc=0.0, size_shares=0.0, entry_price=0.30,
        )
        assert status == "won"
        assert pnl == 2.33  # (1.0 - 0.30) / 0.30 * 1.0
