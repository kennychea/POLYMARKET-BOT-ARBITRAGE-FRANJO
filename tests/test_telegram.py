"""Tests for infra.telegram — alert formatting and sending."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from infra.telegram import (
    _TELEGRAM_API,
    format_scan_alert,
    format_trade_alert,
    send_alert,
)
from infra.types import TradingSignal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def _patch_cfg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake Telegram credentials into infra.config."""
    monkeypatch.setattr("infra.config.TELEGRAM_BOT_TOKEN", "FAKE_TOKEN_123")
    monkeypatch.setattr("infra.config.TELEGRAM_CHAT_ID", "99999")


@pytest.fixture()
def sample_signal() -> TradingSignal:
    return TradingSignal(
        market_id="0xabc123",
        question="Will BTC reach $100k by June 2026?",
        side="YES",
        agent_probability=0.72,
        market_probability=0.55,
        edge_net=0.12,
        confidence=8,
        tradeable=True,
        news_context="Bitcoin rallying after ETF inflows.",
        timestamp=datetime(2026, 3, 29, 14, 30),
    )


# ---------------------------------------------------------------------------
# send_alert
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("_patch_cfg")
@patch("infra.telegram.requests.post")
def test_send_alert_calls_correct_url(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(raise_for_status=MagicMock())

    send_alert("hello")

    expected_url = _TELEGRAM_API.format(token="FAKE_TOKEN_123")
    mock_post.assert_called_once()
    assert mock_post.call_args[0][0] == expected_url


@pytest.mark.usefixtures("_patch_cfg")
@patch("infra.telegram.requests.post")
def test_send_alert_payload(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(raise_for_status=MagicMock())

    send_alert("test message")

    payload = mock_post.call_args[1]["json"]
    assert payload["chat_id"] == "99999"
    assert payload["text"] == "test message"
    assert payload["parse_mode"] == "HTML"


@pytest.mark.usefixtures("_patch_cfg")
@patch("infra.telegram.requests.post")
def test_send_alert_handles_request_exception(mock_post: MagicMock) -> None:
    mock_post.side_effect = requests.RequestException("connection error")

    # Must not raise
    send_alert("should not crash")


@pytest.mark.usefixtures("_patch_cfg")
@patch("infra.telegram.requests.post")
def test_token_interpolation_in_url(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(raise_for_status=MagicMock())

    send_alert("ping")

    url_called = mock_post.call_args[0][0]
    assert "FAKE_TOKEN_123" in url_called
    assert "{token}" not in url_called


# ---------------------------------------------------------------------------
# format_trade_alert
# ---------------------------------------------------------------------------

def test_format_trade_alert_yes_side(sample_signal: TradingSignal) -> None:
    msg = format_trade_alert(sample_signal, size_usdc=25.0, entry_price=0.550)

    assert "YES" in msg
    assert "🟢" in msg
    assert "BTC" in msg
    assert "12.0%" in msg      # edge_net formatted as %
    assert "$25.00" in msg     # size
    assert "0xabc123" in msg   # market_id


def test_format_trade_alert_no_side(sample_signal: TradingSignal) -> None:
    sample_signal.side = "NO"
    msg = format_trade_alert(sample_signal, size_usdc=10.0, entry_price=0.450)

    assert "NO" in msg
    assert "🔴" in msg


# ---------------------------------------------------------------------------
# format_scan_alert
# ---------------------------------------------------------------------------

def test_format_scan_alert_counts() -> None:
    msg = format_scan_alert(markets_scanned=120, opportunities_found=3, trades_placed=1)

    assert "120" in msg
    assert "3" in msg
    assert "1" in msg
    assert "Scan complete" in msg
