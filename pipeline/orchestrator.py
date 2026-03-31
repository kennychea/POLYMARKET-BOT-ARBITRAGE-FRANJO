"""Main trading loop — wires fetcher → news → scorer into a single cycle.

Entry points:
  run_single_cycle(paper=True) → dict   (one pass)
  run_loop(paper=True)         → None   (continuous, CYCLE_INTERVAL_SECONDS)
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

import infra.config as cfg
import infra.db as db
import infra.telegram as tg
from core.fetcher import get_tradeable_markets
from core.news import build_news_context
from core.scorer import score_and_evaluate
from infra.types import TradingSignal

# Execution layer — optional, required only for live mode
try:
    from execution.clob import get_wallet_balance, init_clob_client, place_limit_order
    from execution.orders import cancel_stale_orders, record_fill
    from execution.portfolio import get_portfolio_snapshot, run_resolution_cycle
    from execution.sizing import compute_position_size

    _EXECUTION_AVAILABLE = True
except ImportError:
    _EXECUTION_AVAILABLE = False

logger = logging.getLogger(__name__)

_NEWS_DELAY = 1.0       # seconds between news fetches (rate limit Perplexity)
_SCORER_DELAY = 0.5     # seconds between scorer calls (rate limit Claude API)


def run_single_cycle(paper: bool = True) -> dict[str, Any]:
    """Run one full scan cycle: fetch → news → score → act.

    Returns a summary dict with scanned/opportunity/signal counts.
    """
    cycle_start = time.monotonic()
    timestamp = datetime.now(UTC)
    logger.info("cycle_start", extra={"paper": paper, "timestamp": timestamp.isoformat()})

    # Step 1: Fetch tradeable markets
    markets = get_tradeable_markets()
    total_markets = len(markets)

    if total_markets == 0:
        logger.info("cycle_complete", extra={"scanned": 0, "opportunities": 0, "duration_sec": 0.0})
        db.log_scan(markets_scanned=0, opportunities_found=0, trades_placed=0)
        tg.send_alert(tg.format_scan_alert(0, 0, 0))
        return {"markets_scanned": 0, "opportunities": 0, "signals_sent": 0, "signals": []}

    # Step 2 + 3: For each market, gather news + score
    tradeable_signals: list[TradingSignal] = []

    for idx, market in enumerate(markets):
        logger.info(
            "scoring_market",
            extra={"progress": f"{idx + 1}/{total_markets}", "question": market.question[:60]},
        )

        # Fetch news context (with rate limiting)
        try:
            news_context = build_news_context(market.question)
        except Exception:
            logger.warning("news_fetch_error", extra={"market_id": market.market_id}, exc_info=True)
            news_context = ""

        if idx > 0:
            time.sleep(_NEWS_DELAY)

        # Score market (with rate limiting)
        try:
            signal = score_and_evaluate(market, news_context)
        except Exception:
            logger.warning("scorer_error", extra={"market_id": market.market_id}, exc_info=True)
            signal = None

        time.sleep(_SCORER_DELAY)

        if signal is not None:
            tradeable_signals.append(signal)

        logger.info(
            "market_evaluated",
            extra={
                "market_id": market.market_id,
                "tradeable": signal is not None,
                "edge": round(signal.edge_net, 4) if signal else 0.0,
            },
        )

    # Step 4 + 5: Sort by edge and cap at MAX_SIMULTANEOUS_POSITIONS
    tradeable_signals.sort(key=lambda s: s.edge_net, reverse=True)
    selected = tradeable_signals[: cfg.MAX_SIMULTANEOUS_POSITIONS]

    # Step 6: Act on selected signals
    signals_sent = 0

    if not paper and not _EXECUTION_AVAILABLE:
        raise NotImplementedError(
            "Live trading requires execution/ modules (sizing, clob, orders)"
        )

    conn: sqlite3.Connection | None = None
    try:
        if not paper:
            conn = sqlite3.connect(cfg.DB_PATH)
            conn.row_factory = sqlite3.Row
            snapshot = get_portfolio_snapshot(conn)
            open_positions = snapshot["open_positions"]
            clob_client = init_clob_client()
            bankroll = get_wallet_balance(clob_client)

        for signal in selected:
            if paper:
                db.log_trade(signal, size_usdc=0.0, entry_price=signal.market_probability)
                formatted = tg.format_trade_alert(
                    signal, size_usdc=0.0, entry_price=signal.market_probability,
                )
                alert_msg = f"[PAPER] {formatted}"
                tg.send_alert(alert_msg)
                signals_sent += 1
            else:
                assert conn is not None
                size = compute_position_size(
                    signal, bankroll, open_positions, conn,
                )
                if size < cfg.MIN_TRADE_SIZE:
                    logger.info("live_size_below_min", extra={
                        "market_id": signal.market_id, "size": size,
                    })
                    continue

                order_result = place_limit_order(
                    clob_client, signal.market_id, signal.side, size,
                )

                if order_result.status == "placed":
                    record_fill(conn, signal, order_result)
                    signals_sent += 1
                    logger.info("live_order_placed", extra={
                        "market_id": signal.market_id,
                        "size_usdc": size,
                        "order_id": order_result.order_id,
                    })
                else:
                    logger.warning("live_order_not_placed", extra={
                        "market_id": signal.market_id,
                        "status": order_result.status,
                        "reason": order_result.reason,
                    })
    finally:
        if conn is not None:
            conn.close()

    # Step 7 + 8: Log scan summary
    duration = time.monotonic() - cycle_start
    db.log_scan(
        markets_scanned=total_markets,
        opportunities_found=len(tradeable_signals),
        trades_placed=signals_sent,
    )
    tg.send_alert(tg.format_scan_alert(total_markets, len(tradeable_signals), signals_sent))

    logger.info(
        "cycle_complete",
        extra={
            "scanned": total_markets,
            "opportunities": len(tradeable_signals),
            "signals_sent": signals_sent,
            "duration_sec": round(duration, 2),
        },
    )

    # Step 8.5: Cancel stale open orders (live only)
    if not paper and _EXECUTION_AVAILABLE:
        try:
            stale_client = init_clob_client()
            cancelled = cancel_stale_orders(stale_client)
            logger.info("stale_orders_cleaned", extra={"cancelled": cancelled})
        except Exception:
            logger.warning("stale_orders_cleanup_error", exc_info=True)

    # Step 9: Resolution check — close positions on resolved markets
    if not paper and _EXECUTION_AVAILABLE:
        res_conn = sqlite3.connect(cfg.DB_PATH)
        res_conn.row_factory = sqlite3.Row
        try:
            res_client = init_clob_client()
            closed = run_resolution_cycle(res_conn, res_client)
            if closed > 0:
                logger.info("resolution_cycle_closed", extra={"closed": closed})
        except Exception:
            logger.warning("resolution_cycle_error", exc_info=True)
        finally:
            res_conn.close()

    return {
        "markets_scanned": total_markets,
        "opportunities": len(tradeable_signals),
        "signals_sent": signals_sent,
        "signals": selected,
    }


def run_loop(paper: bool = True, interval: int = cfg.CYCLE_INTERVAL_SECONDS) -> None:
    """Run scan cycles in a loop with a sleep interval between each.

    Catches KeyboardInterrupt for graceful shutdown.
    Catches any exception within a cycle to keep the loop alive.
    """
    logger.info("loop_start", extra={"paper": paper, "interval": interval})
    db.init_db()

    try:
        while True:
            try:
                run_single_cycle(paper=paper)
            except Exception:
                logger.error("cycle_error", exc_info=True)
            logger.info("loop_sleeping", extra={"interval": interval})
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("loop_shutdown_requested")


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Polymarket Agent")
    parser.add_argument("--paper", action="store_true", default=True, help="Paper trading mode")
    parser.add_argument("--live", action="store_true", help="Live trading mode")
    parser.add_argument("--once", action="store_true", help="Run single cycle then exit")
    parser.add_argument("--interval", type=int, default=cfg.CYCLE_INTERVAL_SECONDS)
    args = parser.parse_args()

    paper = not args.live

    db.init_db()
    if args.once:
        run_single_cycle(paper=paper)
    else:
        run_loop(paper=paper, interval=args.interval)
