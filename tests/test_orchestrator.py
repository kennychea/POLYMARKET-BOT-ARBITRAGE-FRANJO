"""Tests for pipeline/orchestrator.py — main trading loop.

All external dependencies (fetcher, news, scorer, db, telegram) are mocked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from core.fetcher import MarketData
from infra.types import TradingSignal
from pipeline.orchestrator import run_single_cycle


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_market(market_id: str = "0xabc", question: str = "Will X?", **kw: object) -> MarketData:
    defaults = dict(
        market_id=market_id,
        question=question,
        yes_price=0.50,
        no_price=0.50,
        spread=0.02,
        volume=10_000.0,
        days_to_resolution=14.0,
        end_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category="politics",
        tags=["politics"],
    )
    defaults.update(kw)
    return MarketData(**defaults)  # type: ignore[arg-type]


def _make_signal(
    market_id: str = "0xabc",
    edge_net: float = 0.10,
    tradeable: bool = True,
    **kw: object,
) -> TradingSignal:
    defaults = dict(
        market_id=market_id,
        question="Will X?",
        side="YES",
        agent_probability=0.65,
        market_probability=0.50,
        edge_net=edge_net,
        confidence=7,
        tradeable=tradeable,
        news_context="news",
        timestamp=datetime.now(timezone.utc),
    )
    defaults.update(kw)
    return TradingSignal(**defaults)  # type: ignore[arg-type]


# Shared patch targets
_PATCHES = {
    "fetcher": "pipeline.orchestrator.get_tradeable_markets",
    "news": "pipeline.orchestrator.build_news_context",
    "scorer": "pipeline.orchestrator.score_and_evaluate",
    "db_log_trade": "pipeline.orchestrator.db.log_trade",
    "db_log_scan": "pipeline.orchestrator.db.log_scan",
    "tg_send": "pipeline.orchestrator.tg.send_alert",
    "tg_trade_fmt": "pipeline.orchestrator.tg.format_trade_alert",
    "tg_scan_fmt": "pipeline.orchestrator.tg.format_scan_alert",
    "sleep": "pipeline.orchestrator.time.sleep",
}


def _patch_all() -> dict[str, MagicMock]:
    """Create patches for all external dependencies. Returns name→mock dict."""
    return {name: patch(target) for name, target in _PATCHES.items()}


# ── Tests ────────────────────────────────────────────────────────────────────


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan summary")
@patch(_PATCHES["tg_trade_fmt"], return_value="trade alert")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["db_log_trade"], return_value=1)
@patch(_PATCHES["scorer"])
@patch(_PATCHES["news"], return_value="news context")
@patch(_PATCHES["fetcher"])
def test_paper_mode_one_tradeable(
    mock_fetcher: MagicMock,
    mock_news: MagicMock,
    mock_scorer: MagicMock,
    mock_db_trade: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_trade: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """3 mock markets, 1 tradeable → correct summary dict."""
    markets = [_make_market(market_id=f"0x{i}") for i in range(3)]
    mock_fetcher.return_value = markets

    signal = _make_signal(market_id="0x1", edge_net=0.12)
    mock_scorer.side_effect = [None, signal, None]

    result = run_single_cycle(paper=True)

    assert result["markets_scanned"] == 3
    assert result["opportunities"] == 1
    assert result["signals_sent"] == 1
    assert len(result["signals"]) == 1
    assert result["signals"][0].market_id == "0x1"


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan summary")
@patch(_PATCHES["tg_trade_fmt"], return_value="trade alert")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["db_log_trade"], return_value=1)
@patch(_PATCHES["scorer"])
@patch(_PATCHES["news"], return_value="news")
@patch(_PATCHES["fetcher"])
def test_paper_mode_logs_to_db(
    mock_fetcher: MagicMock,
    mock_news: MagicMock,
    mock_scorer: MagicMock,
    mock_db_trade: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_trade: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """Paper mode: tradeable signal is logged to DB."""
    mock_fetcher.return_value = [_make_market()]
    signal = _make_signal()
    mock_scorer.return_value = signal

    run_single_cycle(paper=True)

    mock_db_trade.assert_called_once_with(signal, size_usdc=0.0, entry_price=signal.market_probability)


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan")
@patch(_PATCHES["tg_trade_fmt"], return_value="trade alert text")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["db_log_trade"], return_value=1)
@patch(_PATCHES["scorer"])
@patch(_PATCHES["news"], return_value="news")
@patch(_PATCHES["fetcher"])
def test_paper_mode_telegram_alert_has_paper_tag(
    mock_fetcher: MagicMock,
    mock_news: MagicMock,
    mock_scorer: MagicMock,
    mock_db_trade: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_trade: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """Paper mode: Telegram alert contains [PAPER] tag."""
    mock_fetcher.return_value = [_make_market()]
    mock_scorer.return_value = _make_signal()

    run_single_cycle(paper=True)

    # First send_alert call is for the trade, second for scan summary
    trade_call = mock_tg_send.call_args_list[0]
    assert "[PAPER]" in trade_call[0][0]


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["db_log_trade"])
@patch(_PATCHES["scorer"], return_value=None)
@patch(_PATCHES["news"], return_value="news")
@patch(_PATCHES["fetcher"])
def test_no_tradeable_markets(
    mock_fetcher: MagicMock,
    mock_news: MagicMock,
    mock_scorer: MagicMock,
    mock_db_trade: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """No tradeable signals → opportunities=0, signals_sent=0."""
    mock_fetcher.return_value = [_make_market(), _make_market(market_id="0x2")]

    result = run_single_cycle(paper=True)

    assert result["opportunities"] == 0
    assert result["signals_sent"] == 0
    mock_db_trade.assert_not_called()


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan")
@patch(_PATCHES["tg_trade_fmt"], return_value="alert")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["db_log_trade"], return_value=1)
@patch(_PATCHES["scorer"])
@patch(_PATCHES["news"], return_value="news")
@patch(_PATCHES["fetcher"])
def test_scorer_fails_one_market_continues(
    mock_fetcher: MagicMock,
    mock_news: MagicMock,
    mock_scorer: MagicMock,
    mock_db_trade: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_trade: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """Scorer throws on one market → continues to next, no crash."""
    markets = [_make_market(market_id=f"0x{i}") for i in range(3)]
    mock_fetcher.return_value = markets

    signal = _make_signal(market_id="0x2")
    mock_scorer.side_effect = [Exception("API down"), None, signal]

    result = run_single_cycle(paper=True)

    assert result["markets_scanned"] == 3
    assert result["opportunities"] == 1
    assert result["signals_sent"] == 1


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["fetcher"], return_value=[])
def test_fetcher_returns_empty(
    mock_fetcher: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """Fetcher returns empty list → scanned=0, clean exit."""
    result = run_single_cycle(paper=True)

    assert result["markets_scanned"] == 0
    assert result["opportunities"] == 0
    assert result["signals_sent"] == 0


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan")
@patch(_PATCHES["tg_trade_fmt"], return_value="alert")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["db_log_trade"], return_value=1)
@patch(_PATCHES["scorer"])
@patch(_PATCHES["news"], return_value="news")
@patch(_PATCHES["fetcher"])
def test_signals_sorted_by_edge_descending(
    mock_fetcher: MagicMock,
    mock_news: MagicMock,
    mock_scorer: MagicMock,
    mock_db_trade: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_trade: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """Signals are sorted by edge_net descending."""
    markets = [_make_market(market_id=f"0x{i}") for i in range(3)]
    mock_fetcher.return_value = markets

    signals = [
        _make_signal(market_id="0x0", edge_net=0.05),
        _make_signal(market_id="0x1", edge_net=0.20),
        _make_signal(market_id="0x2", edge_net=0.10),
    ]
    mock_scorer.side_effect = signals

    result = run_single_cycle(paper=True)

    assert [s.market_id for s in result["signals"]] == ["0x1", "0x2", "0x0"]


@patch(_PATCHES["sleep"])
@patch(_PATCHES["tg_scan_fmt"], return_value="scan")
@patch(_PATCHES["tg_trade_fmt"], return_value="alert")
@patch(_PATCHES["tg_send"])
@patch(_PATCHES["db_log_scan"])
@patch(_PATCHES["db_log_trade"], return_value=1)
@patch(_PATCHES["scorer"])
@patch(_PATCHES["news"], return_value="news")
@patch(_PATCHES["fetcher"])
def test_max_simultaneous_positions_cap(
    mock_fetcher: MagicMock,
    mock_news: MagicMock,
    mock_scorer: MagicMock,
    mock_db_trade: MagicMock,
    mock_db_scan: MagicMock,
    mock_tg_send: MagicMock,
    mock_tg_trade: MagicMock,
    mock_tg_scan: MagicMock,
    mock_sleep: MagicMock,
) -> None:
    """At most MAX_SIMULTANEOUS_POSITIONS signals are kept."""
    n_markets = 8
    markets = [_make_market(market_id=f"0x{i}") for i in range(n_markets)]
    mock_fetcher.return_value = markets

    signals = [_make_signal(market_id=f"0x{i}", edge_net=0.10 + i * 0.01) for i in range(n_markets)]
    mock_scorer.side_effect = signals

    result = run_single_cycle(paper=True)

    # MAX_SIMULTANEOUS_POSITIONS = 5
    assert result["opportunities"] == n_markets
    assert result["signals_sent"] == 5
    assert len(result["signals"]) == 5
    # Top 5 by edge: 0x7 (0.17), 0x6 (0.16), 0x5 (0.15), 0x4 (0.14), 0x3 (0.13)
    assert result["signals"][0].market_id == "0x7"
