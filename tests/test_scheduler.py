"""Tests for pipeline.scheduler — all external deps mocked."""
from __future__ import annotations

import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

# Mock infra.config before importing scheduler so it doesn't hit .env
with patch.dict("os.environ", {
    "ANTHROPIC_API_KEY": "test",
    "POLYMARKET_API_KEY": "test",
    "POLYMARKET_PRIVATE_KEY": "test",
    "PERPLEXITY_API_KEY": "test",
    "TELEGRAM_BOT_TOKEN": "test",
    "TELEGRAM_CHAT_ID": "test",
}):
    from pipeline import scheduler


@pytest.fixture(autouse=True)
def _reset_scheduler() -> None:  # type: ignore[misc]
    """Reset global scheduler state between tests."""
    scheduler._scheduler = None
    yield  # type: ignore[misc]
    # Cleanup: stop if still running
    if scheduler._scheduler is not None:
        try:
            scheduler.stop()
        except Exception:
            pass
    scheduler._scheduler = None


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_start_creates_running_scheduler(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """start() should create and start a BackgroundScheduler."""
    sched = scheduler.start(paper=True)
    assert sched.running
    assert scheduler.is_running()
    scheduler.stop()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_start_idempotent(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """Calling start() twice returns the same scheduler."""
    sched1 = scheduler.start(paper=True)
    sched2 = scheduler.start(paper=True)
    assert sched1 is sched2
    scheduler.stop()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_stop_shuts_down(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """stop() should shut down the scheduler."""
    scheduler.start(paper=True)
    assert scheduler.is_running()
    scheduler.stop()
    assert not scheduler.is_running()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_stop_when_not_running(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """stop() when no scheduler is running should be a no-op."""
    scheduler.stop()  # Should not raise
    assert not scheduler.is_running()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_is_running_false_initially(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """is_running() should return False before start()."""
    assert not scheduler.is_running()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_job_registered_with_correct_id(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """The trading_cycle job should be registered."""
    sched = scheduler.start(paper=True)
    job = sched.get_job("trading_cycle")
    assert job is not None
    assert job.name == "Trading Cycle"
    scheduler.stop()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_job_uses_config_interval(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """Job interval should match cfg.CYCLE_INTERVAL_SECONDS."""
    sched = scheduler.start(paper=True)
    job = sched.get_job("trading_cycle")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 900
    scheduler.stop()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_misfire_grace_time(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """Jobs should have misfire_grace_time=300."""
    sched = scheduler.start(paper=True)
    job = sched.get_job("trading_cycle")
    assert job is not None
    assert job.misfire_grace_time == 300
    scheduler.stop()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_signal_handler_calls_stop(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """_signal_handler should call stop() and exit."""
    scheduler.start(paper=True)
    with pytest.raises(SystemExit):
        scheduler._signal_handler(signal.SIGINT, None)
    assert not scheduler.is_running()


@patch("pipeline.scheduler.db")
@patch("pipeline.scheduler.run_single_cycle")
def test_job_listener_logs_errors(mock_cycle: MagicMock, mock_db: MagicMock) -> None:
    """_job_listener should handle error events without raising."""
    event = MagicMock()
    event.exception = RuntimeError("test error")
    scheduler._job_listener(event)  # Should not raise

    event.exception = None
    event.retval = {"markets_scanned": 5}
    scheduler._job_listener(event)  # Should not raise
