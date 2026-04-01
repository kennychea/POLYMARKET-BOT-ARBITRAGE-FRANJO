"""SQLite persistence layer — schema, helpers, calibration."""
from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC
from typing import Any

import infra.config as cfg
from infra.types import CalibrationBucket, TradingSignal

logger = logging.getLogger(__name__)

_CALIBRATION_BUCKETS = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    market_id           TEXT    NOT NULL,
    question            TEXT    NOT NULL,
    side                TEXT    NOT NULL CHECK(side IN ('YES', 'NO')),
    size_usdc           REAL    NOT NULL,
    entry_price         REAL    NOT NULL,
    agent_probability   REAL    NOT NULL,
    market_probability  REAL    NOT NULL,
    edge_net            REAL    NOT NULL,
    confidence          INTEGER NOT NULL,
    order_id            TEXT    NOT NULL DEFAULT '',
    size_shares         REAL    NOT NULL DEFAULT 0.0,
    status              TEXT    NOT NULL DEFAULT 'open'
                            CHECK(status IN ('open', 'won', 'lost', 'void', 'cancelled')),
    exit_price          REAL,
    pnl                 REAL,
    resolution_date     TEXT
);

CREATE TABLE IF NOT EXISTS market_scans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    markets_scanned     INTEGER NOT NULL,
    opportunities_found INTEGER NOT NULL,
    trades_placed       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_bankroll (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    bankroll            REAL    NOT NULL,
    trade_id            INTEGER,
    pnl_delta           REAL    NOT NULL DEFAULT 0.0,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    """Open a connection, commit on success, rollback on error."""
    connection = sqlite3.connect(cfg.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    db_dir = os.path.dirname(cfg.DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with _conn() as con:
        con.executescript(_SCHEMA)
    logger.info("db_initialized", extra={"path": cfg.DB_PATH})


def log_trade(
    signal: TradingSignal,
    size_usdc: float,
    entry_price: float,
    order_id: str = "",
    size_shares: float = 0.0,
) -> int:
    """Insert a new trade record. Returns the assigned trade ID."""
    with _conn() as con:
        cursor = con.execute(
            """
            INSERT INTO trades
                (timestamp, market_id, question, side, size_usdc, entry_price,
                 agent_probability, market_probability, edge_net, confidence,
                 order_id, size_shares, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                signal.timestamp.isoformat(),
                signal.market_id,
                signal.question,
                signal.side,
                size_usdc,
                entry_price,
                signal.agent_probability,
                signal.market_probability,
                signal.edge_net,
                signal.confidence,
                order_id,
                size_shares,
            ),
        )
        trade_id: int = cursor.lastrowid  # type: ignore[assignment]
    logger.info(
        "trade_logged",
        extra={"trade_id": trade_id, "market_id": signal.market_id, "side": signal.side},
    )
    return trade_id


def log_scan(markets_scanned: int, opportunities_found: int, trades_placed: int) -> None:
    """Record one market-scan cycle result."""
    from datetime import datetime

    with _conn() as con:
        con.execute(
            """
            INSERT INTO market_scans
                (timestamp, markets_scanned, opportunities_found, trades_placed)
            VALUES (?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                markets_scanned,
                opportunities_found,
                trades_placed,
            ),
        )
    logger.info(
        "scan_logged",
        extra={
            "markets_scanned": markets_scanned,
            "opportunities_found": opportunities_found,
            "trades_placed": trades_placed,
        },
    )


def update_trade_result(
    trade_id: int,
    status: str,
    exit_price: float | None = None,
    pnl: float | None = None,
    resolution_date: str | None = None,
) -> None:
    """Update trade outcome after market resolution."""
    with _conn() as con:
        con.execute(
            """
            UPDATE trades
            SET status = ?, exit_price = ?, pnl = ?, resolution_date = ?
            WHERE id = ?
            """,
            (status, exit_price, pnl, resolution_date, trade_id),
        )
    logger.info(
        "trade_updated",
        extra={"trade_id": trade_id, "status": status, "pnl": pnl},
    )


def get_open_positions() -> list[dict[str, Any]]:
    """Return all trades with status='open' as dicts."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM trades WHERE status = 'open' ORDER BY timestamp ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_trades() -> list[dict[str, Any]]:
    """Return all trades ordered by timestamp descending."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_scans(limit: int = 200) -> list[dict[str, Any]]:
    """Return recent market scans ordered by timestamp descending."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM market_scans ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def compute_calibration(last_n: int = 100) -> list[CalibrationBucket]:
    """Compute calibration error per probability bucket over the last N resolved trades.

    Buckets are evenly spaced in [0.0, 1.0) with width 1/CALIBRATION_BUCKETS.
    Only 'won' and 'lost' trades are included (skips void/cancelled).
    """
    with _conn() as con:
        rows = con.execute(
            """
            SELECT agent_probability, status
            FROM trades
            WHERE status IN ('won', 'lost')
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (last_n,),
        ).fetchall()

    # bucket_data[i] = list of (predicted_prob, did_win)
    bucket_data: list[list[tuple[float, bool]]] = [
        [] for _ in range(_CALIBRATION_BUCKETS)
    ]
    for row in rows:
        prob: float = float(row["agent_probability"])
        won: bool = row["status"] == "won"
        idx = min(int(prob * _CALIBRATION_BUCKETS), _CALIBRATION_BUCKETS - 1)
        bucket_data[idx].append((prob, won))

    results: list[CalibrationBucket] = []
    for i, entries in enumerate(bucket_data):
        if not entries:
            continue
        bucket_low = i / _CALIBRATION_BUCKETS
        bucket_high = (i + 1) / _CALIBRATION_BUCKETS
        predicted = sum(p for p, _ in entries) / len(entries)
        actual = sum(1 for _, w in entries if w) / len(entries)
        results.append(
            CalibrationBucket(
                bucket_low=bucket_low,
                bucket_high=bucket_high,
                predicted_prob=predicted,
                actual_win_rate=actual,
                count=len(entries),
                error=abs(predicted - actual),
            )
        )

    logger.info(
        "calibration_computed",
        extra={"last_n": last_n, "buckets_with_data": len(results)},
    )
    return results


# ── Paper bankroll ──────────────────────────────────────────────────────────


def get_paper_bankroll() -> float:
    """Return the latest paper bankroll, or PAPER_INITIAL_BANKROLL if none exists."""
    with _conn() as con:
        row = con.execute(
            "SELECT bankroll FROM paper_bankroll ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return cfg.PAPER_INITIAL_BANKROLL
    return float(row["bankroll"])


def update_paper_bankroll(
    trade_id: int | None,
    pnl_delta: float,
    new_bankroll: float,
) -> None:
    """Record a bankroll change after a paper trade or resolution."""
    from datetime import datetime

    with _conn() as con:
        con.execute(
            """
            INSERT INTO paper_bankroll (timestamp, bankroll, trade_id, pnl_delta)
            VALUES (?, ?, ?, ?)
            """,
            (datetime.now(UTC).isoformat(), new_bankroll, trade_id, pnl_delta),
        )
    logger.info(
        "paper_bankroll_updated",
        extra={"trade_id": trade_id, "pnl_delta": pnl_delta, "bankroll": new_bankroll},
    )


def get_paper_bankroll_history() -> list[dict[str, Any]]:
    """Return full paper bankroll history, newest first."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM paper_bankroll ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def paper_kelly_size(
    bankroll: float,
    edge: float,
    market_price: float,
    fraction: float = 0.25,
    max_pct: float = 0.10,
) -> float:
    """Quarter-Kelly sizing for paper trades. No execution/ dependency.

    Returns 0.0 for invalid inputs. Caps at max_pct * bankroll.
    Enforces MIN_TRADE_SIZE floor.
    """
    if edge <= 0 or market_price <= 0 or market_price >= 1 or bankroll <= 0:
        return 0.0

    b = (1 / market_price) - 1          # implied odds
    p = market_price + edge             # estimated true prob
    q = 1 - p

    kelly_raw = (b * p - q) / b
    if kelly_raw <= 0:
        return 0.0

    size = bankroll * kelly_raw * fraction
    size = min(size, bankroll * max_pct)
    size = round(size, 2)

    return max(size, cfg.MIN_TRADE_SIZE) if size >= cfg.MIN_TRADE_SIZE else 0.0
