"""APScheduler-based scheduler for periodic trading cycles.

Entry point:
  python -m pipeline.scheduler --paper
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler

import infra.config as cfg
import infra.db as db
from pipeline.orchestrator import run_single_cycle

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def _job_listener(event: JobExecutionEvent) -> None:
    """Log job execution results."""
    if event.exception:
        logger.error("cycle_job_failed", exc_info=event.exception)
    else:
        logger.info("cycle_job_completed", extra={"retval": str(event.retval)[:200]})


def start(paper: bool = True) -> BackgroundScheduler:
    """Create and start the background scheduler.

    Returns the scheduler instance.  Calling start() when a scheduler is
    already running is a no-op and returns the existing instance.
    """
    global _scheduler  # noqa: PLW0603

    with _lock:
        if _scheduler is not None and _scheduler.running:
            logger.info("scheduler_already_running")
            return _scheduler

        db.init_db()

        scheduler = BackgroundScheduler(
            job_defaults={"misfire_grace_time": 300},
        )
        scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        scheduler.add_job(
            run_single_cycle,
            trigger="interval",
            seconds=cfg.CYCLE_INTERVAL_SECONDS,
            kwargs={"paper": paper},
            id="trading_cycle",
            name="Trading Cycle",
        )
        scheduler.start()
        _scheduler = scheduler

        logger.info(
            "scheduler_started",
            extra={"paper": paper, "interval": cfg.CYCLE_INTERVAL_SECONDS},
        )
        return scheduler


def stop() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler  # noqa: PLW0603

    with _lock:
        if _scheduler is not None and _scheduler.running:
            _scheduler.shutdown(wait=True)
            logger.info("scheduler_stopped")
        _scheduler = None


def is_running() -> bool:
    """Return True if the scheduler is currently running."""
    with _lock:
        return _scheduler is not None and _scheduler.running


def _signal_handler(signum: int, _frame: object) -> None:
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    sig_name = signal.Signals(signum).name
    logger.info("shutdown_signal_received", extra={"signal": sig_name})
    stop()
    sys.exit(0)


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Polymarket Agent Scheduler")
    parser.add_argument("--paper", action="store_true", default=True, help="Paper trading mode")
    parser.add_argument("--live", action="store_true", help="Live trading mode")
    args = parser.parse_args()

    paper = not args.live

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    start(paper=paper)

    # Run first cycle immediately, then let APScheduler handle the rest
    logger.info("running_initial_cycle")
    try:
        run_single_cycle(paper=paper)
    except Exception:
        logger.error("initial_cycle_error", exc_info=True)

    # Block main thread until scheduler stops
    try:
        threading.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("main_thread_interrupted")
        stop()


if __name__ == "__main__":
    main()
