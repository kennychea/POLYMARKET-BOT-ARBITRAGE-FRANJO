"""Tests for infra/db.py — SQLite persistence layer."""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

import infra.config as cfg
import infra.db as db_module
from infra.db import (
    compute_calibration,
    get_open_positions,
    init_db,
    log_scan,
    log_trade,
    update_trade_result,
)
from infra.types import TradingSignal


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_signal(**overrides: object) -> TradingSignal:
    defaults = dict(
        market_id="mkt-1",
        question="Will X happen?",
        side="YES",
        agent_probability=0.70,
        market_probability=0.55,
        edge_net=0.08,
        confidence=7,
        tradeable=True,
        news_context="test context",
        timestamp=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return TradingSignal(**defaults)  # type: ignore[arg-type]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _memory_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shared in-memory DB: patch _conn to reuse a single connection."""
    shared_conn = sqlite3.connect(":memory:")
    shared_conn.row_factory = sqlite3.Row

    @contextmanager
    def _shared_conn() -> Generator[sqlite3.Connection, None, None]:
        try:
            yield shared_conn
            shared_conn.commit()
        except Exception:
            shared_conn.rollback()
            raise

    monkeypatch.setattr(cfg, "DB_PATH", ":memory:")
    monkeypatch.setattr(db_module, "_conn", _shared_conn)
    init_db()
    yield  # type: ignore[func-returns-value]
    shared_conn.close()


# ── init_db ───────────────────────────────────────────────────────────────────


def test_init_db_creates_tables() -> None:
    """Tables exist after init_db."""
    with db_module._conn() as con:
        tables = {
            r["name"]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "trades" in tables
    assert "market_scans" in tables


def test_init_db_idempotent() -> None:
    """Calling init_db twice does not raise."""
    init_db()
    init_db()


# ── log_trade ─────────────────────────────────────────────────────────────────


def test_log_trade_returns_id() -> None:
    sig = _make_signal()
    trade_id = log_trade(sig, size_usdc=50.0, entry_price=0.55)
    assert isinstance(trade_id, int)
    assert trade_id >= 1


def test_log_trade_round_trip() -> None:
    """Inserted trade is readable and fields match."""
    sig = _make_signal(market_id="mkt-rt", side="NO", agent_probability=0.80)
    tid = log_trade(sig, size_usdc=42.0, entry_price=0.20)

    with db_module._conn() as con:
        row = con.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
    assert row is not None
    assert row["market_id"] == "mkt-rt"
    assert row["side"] == "NO"
    assert row["size_usdc"] == pytest.approx(42.0)
    assert row["entry_price"] == pytest.approx(0.20)
    assert row["agent_probability"] == pytest.approx(0.80)
    assert row["status"] == "open"


def test_log_trade_multiple_ids_unique() -> None:
    """Successive inserts get distinct IDs."""
    id1 = log_trade(_make_signal(), 10.0, 0.50)
    id2 = log_trade(_make_signal(), 20.0, 0.60)
    assert id1 != id2


# ── log_scan ──────────────────────────────────────────────────────────────────


def test_log_scan_inserts_row() -> None:
    log_scan(markets_scanned=100, opportunities_found=3, trades_placed=1)

    with db_module._conn() as con:
        row = con.execute("SELECT * FROM market_scans ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["markets_scanned"] == 100
    assert row["opportunities_found"] == 3
    assert row["trades_placed"] == 1


# ── update_trade_result ───────────────────────────────────────────────────────


def test_update_trade_result_sets_fields() -> None:
    tid = log_trade(_make_signal(), 50.0, 0.55)
    update_trade_result(tid, status="won", exit_price=1.0, pnl=22.5, resolution_date="2026-04-01")

    with db_module._conn() as con:
        row = con.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
    assert row["status"] == "won"
    assert row["exit_price"] == pytest.approx(1.0)
    assert row["pnl"] == pytest.approx(22.5)
    assert row["resolution_date"] == "2026-04-01"


def test_update_trade_result_lost() -> None:
    tid = log_trade(_make_signal(), 50.0, 0.55)
    update_trade_result(tid, status="lost", exit_price=0.0, pnl=-50.0)

    with db_module._conn() as con:
        row = con.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()
    assert row["status"] == "lost"
    assert row["pnl"] == pytest.approx(-50.0)


# ── get_open_positions ────────────────────────────────────────────────────────


def test_get_open_positions_empty() -> None:
    assert get_open_positions() == []


def test_get_open_positions_returns_open_only() -> None:
    tid1 = log_trade(_make_signal(market_id="open-1"), 10.0, 0.50)
    tid2 = log_trade(_make_signal(market_id="closed-1"), 20.0, 0.60)
    update_trade_result(tid2, status="won", exit_price=1.0, pnl=8.0)

    positions = get_open_positions()
    assert len(positions) == 1
    assert positions[0]["market_id"] == "open-1"


def test_get_open_positions_returns_dicts() -> None:
    log_trade(_make_signal(), 10.0, 0.50)
    positions = get_open_positions()
    assert isinstance(positions[0], dict)
    assert "market_id" in positions[0]


# ── compute_calibration ──────────────────────────────────────────────────────


def test_compute_calibration_empty() -> None:
    """No resolved trades → empty list."""
    assert compute_calibration() == []


def test_compute_calibration_ignores_open_void() -> None:
    """Open and void trades are excluded from calibration."""
    tid1 = log_trade(_make_signal(agent_probability=0.70), 10.0, 0.50)
    tid2 = log_trade(_make_signal(agent_probability=0.70), 10.0, 0.50)
    # Leave tid1 open, mark tid2 void
    update_trade_result(tid2, status="void")
    assert compute_calibration() == []


def test_compute_calibration_bucketing() -> None:
    """Trades are placed in the correct probability buckets."""
    # prob=0.15 → bucket [0.1, 0.2), prob=0.85 → bucket [0.8, 0.9)
    tid1 = log_trade(_make_signal(agent_probability=0.15), 10.0, 0.50)
    update_trade_result(tid1, status="won", exit_price=1.0, pnl=5.0)

    tid2 = log_trade(_make_signal(agent_probability=0.85), 10.0, 0.50)
    update_trade_result(tid2, status="lost", exit_price=0.0, pnl=-10.0)

    buckets = compute_calibration()
    assert len(buckets) == 2

    low_bucket = next(b for b in buckets if b.bucket_low == pytest.approx(0.1))
    assert low_bucket.bucket_high == pytest.approx(0.2)
    assert low_bucket.predicted_prob == pytest.approx(0.15)
    assert low_bucket.actual_win_rate == pytest.approx(1.0)  # 1 won / 1 total
    assert low_bucket.count == 1

    high_bucket = next(b for b in buckets if b.bucket_low == pytest.approx(0.8))
    assert high_bucket.actual_win_rate == pytest.approx(0.0)  # 0 won / 1 total


def test_compute_calibration_multiple_in_same_bucket() -> None:
    """Multiple trades in one bucket are aggregated correctly."""
    for prob, status in [(0.72, "won"), (0.74, "won"), (0.78, "lost")]:
        tid = log_trade(_make_signal(agent_probability=prob), 10.0, 0.50)
        update_trade_result(tid, status=status, exit_price=1.0 if status == "won" else 0.0, pnl=5.0 if status == "won" else -10.0)

    buckets = compute_calibration()
    assert len(buckets) == 1
    b = buckets[0]
    assert b.bucket_low == pytest.approx(0.7)
    assert b.count == 3
    assert b.predicted_prob == pytest.approx((0.72 + 0.74 + 0.78) / 3)
    assert b.actual_win_rate == pytest.approx(2 / 3)
    assert b.error == pytest.approx(abs(b.predicted_prob - b.actual_win_rate))


def test_compute_calibration_prob_1_0_edge_case() -> None:
    """Probability=1.0 goes into the last bucket, not out of bounds."""
    tid = log_trade(_make_signal(agent_probability=1.0), 10.0, 0.50)
    update_trade_result(tid, status="won", exit_price=1.0, pnl=10.0)

    buckets = compute_calibration()
    assert len(buckets) == 1
    assert buckets[0].bucket_low == pytest.approx(0.9)
    assert buckets[0].bucket_high == pytest.approx(1.0)
