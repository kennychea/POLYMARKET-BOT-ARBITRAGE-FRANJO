"""Standalone market resolution checker for paper (and live) trades.

Reads open trades from DB, checks Gamma API for resolution,
updates status/PnL in DB.  No dependency on execution/ layer.

Usage:
    python -m core.resolver              # resolve all open trades
    python -m core.resolver --dry-run    # preview without DB writes
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from typing import Any

import requests

import infra.config as cfg
from infra.db import (
    get_open_positions,
    get_paper_bankroll,
    init_db,
    update_paper_bankroll,
    update_trade_result,
)
import infra.telegram as tg

logger = logging.getLogger(__name__)

_CLOB_BASE = "https://clob.polymarket.com"
_REQUEST_TIMEOUT = 10


# ── CLOB API helpers ─────────────────────────────────────────────────────────

def fetch_market_resolution(market_id: str) -> dict[str, Any]:
    """Query CLOB API for a single market by conditionId. Returns raw JSON dict.

    The DB stores conditionId as market_id.  CLOB's ``/markets/{conditionId}``
    endpoint returns closed/active flags plus per-token winner booleans which
    is all we need for resolution.
    """
    resp = requests.get(
        f"{_CLOB_BASE}/markets/{market_id}",
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def parse_resolution(data: dict[str, Any]) -> tuple[bool, str | None]:
    """Determine if market is resolved and which side won.

    Returns (is_resolved, outcome) where outcome is 'YES' or 'NO'.

    Resolution signal: ``closed=True`` **and** one token has ``winner=True``.
    A market can be ``closed`` but not yet resolved (halted / waiting UMA),
    so we require an explicit winner.
    """
    if not data.get("closed"):
        return False, None

    tokens = data.get("tokens")
    if tokens and isinstance(tokens, list):
        for t in tokens:
            if isinstance(t, dict) and t.get("winner"):
                return True, str(t.get("outcome", "Yes")).upper()

    # closed but no winner yet → not resolved
    return False, None


# ── PnL calculation ──────────────────────────────────────────────────────────

def calculate_pnl(
    side: str,
    outcome: str,
    size_usdc: float,
    size_shares: float,
    entry_price: float,
) -> tuple[str, float, float]:
    """Compute trade result.

    Returns (status, exit_price, pnl).
    For paper trades with size_usdc=0 (legacy), PnL is computed notionally.
    For paper trades with real sizes, shares-based PnL is used.
    """
    won = side == outcome

    if won:
        exit_price = 1.0
        if size_shares > 0:
            pnl = size_shares * 1.0 - size_usdc
        else:
            # Legacy paper trade (size_usdc=0): notional gain
            pnl = round((1.0 - entry_price) / entry_price * max(size_usdc, 1.0), 2)
    else:
        exit_price = 0.0
        if size_usdc > 0:
            pnl = -size_usdc
        else:
            # Legacy paper trade (size_usdc=0): notional $1 loss
            pnl = -1.0

    return "won" if won else "lost", exit_price, round(pnl, 2)


# ── Main resolution logic ───────────────────────────────────────────────────

def resolve_open_trades(*, dry_run: bool = False) -> dict[str, Any]:
    """Check all open trades for market resolution.

    Returns summary dict with counts and details.
    """
    open_trades = get_open_positions()

    resolved_count = 0
    won_count = 0
    lost_count = 0
    total_pnl = 0.0
    skipped = 0
    errors = 0
    details: list[dict[str, Any]] = []

    for trade in open_trades:
        trade_id = trade["id"]
        market_id = trade["market_id"]
        question = trade["question"][:80]

        try:
            data = fetch_market_resolution(market_id)
        except Exception as exc:
            logger.warning(
                "resolution_api_error",
                extra={"trade_id": trade_id, "market_id": market_id, "error": str(exc)},
            )
            errors += 1
            continue

        is_resolved, outcome = parse_resolution(data)

        if not is_resolved or outcome is None:
            logger.debug(
                "trade_not_resolved",
                extra={"trade_id": trade_id, "market_id": market_id},
            )
            skipped += 1
            continue

        status, exit_price, pnl = calculate_pnl(
            side=trade["side"],
            outcome=outcome,
            size_usdc=trade["size_usdc"],
            size_shares=trade["size_shares"],
            entry_price=trade["entry_price"],
        )

        resolution_date = datetime.now(UTC).isoformat()

        detail = {
            "trade_id": trade_id,
            "question": question,
            "side": trade["side"],
            "outcome": outcome,
            "status": status,
            "entry_price": trade["entry_price"],
            "exit_price": exit_price,
            "pnl": pnl,
        }
        details.append(detail)

        if not dry_run:
            update_trade_result(
                trade_id=trade_id,
                status=status,
                exit_price=exit_price,
                pnl=pnl,
                resolution_date=resolution_date,
            )

            # Update paper bankroll: add back the original stake + pnl
            # On entry we deducted size_usdc; now we return size_usdc + pnl
            bankroll_before = get_paper_bankroll()
            bankroll_delta = trade["size_usdc"] + pnl  # won: +profit, lost: 0 (stake gone)
            new_bankroll = round(bankroll_before + bankroll_delta, 2)
            update_paper_bankroll(
                trade_id=trade_id,
                pnl_delta=pnl,
                new_bankroll=new_bankroll,
            )

            # Telegram resolution alert
            icon = "W" if status == "won" else "L"
            sign = "+" if pnl >= 0 else ""
            tg.send_alert(
                f"[PAPER] Resolved: {question} → {icon} {status.upper()}\n"
                f"PnL: {sign}${pnl:.2f} | Bankroll: ${new_bankroll:.2f}"
            )

        logger.info(
            "trade_resolved",
            extra={
                "trade_id": trade_id,
                "status": status,
                "pnl": pnl,
                "outcome": outcome,
                "dry_run": dry_run,
            },
        )

        resolved_count += 1
        total_pnl += pnl
        if status == "won":
            won_count += 1
        else:
            lost_count += 1

    summary = {
        "total_open": len(open_trades),
        "resolved": resolved_count,
        "won": won_count,
        "lost": lost_count,
        "skipped": skipped,
        "errors": errors,
        "total_pnl": round(total_pnl, 2),
        "dry_run": dry_run,
        "details": details,
    }

    logger.info("resolution_summary", extra={k: v for k, v in summary.items() if k != "details"})
    return summary


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_summary(summary: dict[str, Any]) -> None:
    """Pretty-print resolution summary to stdout."""
    mode = "[DRY-RUN] " if summary["dry_run"] else ""
    total = summary["total_open"]
    resolved = summary["resolved"]
    won = summary["won"]
    lost = summary["lost"]
    pnl = summary["total_pnl"]
    skipped = summary["skipped"]
    errors = summary["errors"]

    print(f"\n{mode}Resolution Summary")
    print(f"  Open trades checked: {total}")
    print(f"  Resolved: {resolved}/{total} ({won} won, {lost} lost)")
    print(f"  Still open: {skipped}")
    if errors:
        print(f"  API errors: {errors}")
    sign = "+" if pnl >= 0 else ""
    print(f"  Total PnL: {sign}${pnl:.2f}")

    if summary["details"]:
        print("\n  Details:")
        for d in summary["details"]:
            icon = "W" if d["status"] == "won" else "L"
            sign_d = "+" if d["pnl"] >= 0 else ""
            print(f"    [{icon}] #{d['trade_id']} {d['question']} | {d['side']}→{d['outcome']} | {sign_d}${d['pnl']:.2f}")
    print()


def cleanup_duplicate_trades(*, dry_run: bool = False) -> dict[str, int]:
    """Remove duplicate trades, keeping only the first per (market_id, side).

    Returns {"removed": N, "kept": M}.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(cfg.DB_PATH)
    conn.row_factory = _sqlite3.Row

    # Find the earliest trade id per (market_id, side)
    groups = conn.execute(
        """
        SELECT market_id, side, MIN(id) AS keep_id, COUNT(*) AS cnt
        FROM trades
        GROUP BY market_id, side
        HAVING cnt > 1
        """
    ).fetchall()

    keep_ids: set[int] = set()
    for g in groups:
        keep_ids.add(g["keep_id"])

    # Collect ids to delete
    to_delete: list[dict[str, Any]] = []
    for g in groups:
        dupes = conn.execute(
            """
            SELECT id, timestamp, question, side
            FROM trades
            WHERE market_id = ? AND side = ? AND id != ?
            ORDER BY id
            """,
            (g["market_id"], g["side"], g["keep_id"]),
        ).fetchall()
        for d in dupes:
            to_delete.append(dict(d))
            logger.info(
                "duplicate_trade",
                extra={
                    "action": "delete" if not dry_run else "would_delete",
                    "trade_id": d["id"],
                    "question": d["question"][:50],
                    "side": d["side"],
                },
            )

    if not dry_run and to_delete:
        delete_ids = [d["id"] for d in to_delete]
        placeholders = ",".join("?" for _ in delete_ids)
        conn.execute(f"DELETE FROM trades WHERE id IN ({placeholders})", delete_ids)  # noqa: S608
        conn.commit()

    total_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()

    removed = len(to_delete)
    kept = total_trades if not dry_run else total_trades - removed

    mode = "[DRY-RUN] " if dry_run else ""
    print(f"\n{mode}Duplicate Cleanup")
    print(f"  Removed: {removed} duplicate trades")
    print(f"  Kept: {kept} unique trades\n")

    logger.info(
        "cleanup_dupes_done",
        extra={"removed": removed, "kept": kept, "dry_run": dry_run},
    )
    return {"removed": removed, "kept": kept}


def _print_bankroll() -> None:
    """Print paper bankroll summary."""
    from infra.db import get_all_trades, get_paper_bankroll_history

    bankroll = get_paper_bankroll()
    history = get_paper_bankroll_history()

    # Compute stats from resolved trades
    all_trades = get_all_trades()
    resolved = [t for t in all_trades if t["status"] in ("won", "lost")]
    total_trades = len(resolved)
    won_count = sum(1 for t in resolved if t["status"] == "won")
    total_pnl = sum(t.get("pnl", 0) or 0 for t in resolved)
    winrate = (won_count / total_trades * 100) if total_trades > 0 else 0.0
    roi = (bankroll - cfg.PAPER_INITIAL_BANKROLL) / cfg.PAPER_INITIAL_BANKROLL * 100

    print(f"\n  Paper Bankroll Summary")
    print(f"  {'=' * 40}")
    print(f"  Initial bankroll:  ${cfg.PAPER_INITIAL_BANKROLL:.2f}")
    print(f"  Current bankroll:  ${bankroll:.2f}")
    sign = "+" if total_pnl >= 0 else ""
    print(f"  Total PnL:         {sign}${total_pnl:.2f}")
    print(f"  Resolved trades:   {total_trades}")
    print(f"  Win rate:          {winrate:.1f}% ({won_count}/{total_trades})")
    roi_sign = "+" if roi >= 0 else ""
    print(f"  ROI:               {roi_sign}{roi:.1f}%")

    open_trades = [t for t in all_trades if t["status"] == "open"]
    if open_trades:
        open_exposure = sum(t.get("size_usdc", 0) or 0 for t in open_trades)
        print(f"  Open positions:    {len(open_trades)} (${open_exposure:.2f} exposure)")

    if history:
        print(f"\n  Recent bankroll changes:")
        for entry in history[:10]:
            sign_e = "+" if entry["pnl_delta"] >= 0 else ""
            print(f"    #{entry.get('trade_id', '?'):>4} | {sign_e}${entry['pnl_delta']:.2f} → ${entry['bankroll']:.2f} | {entry['timestamp'][:19]}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve open paper/live trades against Gamma API")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--cleanup-dupes", action="store_true", help="Remove duplicate trades per (market_id, side)")
    parser.add_argument("--bankroll", action="store_true", help="Show paper bankroll summary")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    init_db()

    if args.bankroll:
        _print_bankroll()
        return

    if args.cleanup_dupes:
        cleanup_duplicate_trades(dry_run=args.dry_run)
        return

    summary = resolve_open_trades(dry_run=args.dry_run)
    _print_summary(summary)

    if summary["resolved"] == 0:
        print("No markets resolved yet. Paper trades remain open until their markets close on Polymarket.")


if __name__ == "__main__":
    main()
