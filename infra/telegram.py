"""Telegram alert layer — real-time trade and system notifications."""
from __future__ import annotations

import logging

import requests

import infra.config as cfg
from infra.types import TradingSignal

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_REQUEST_TIMEOUT = 10  # seconds


def send_alert(message: str) -> None:
    """Send a plain-text or HTML message to the configured Telegram chat.

    Failures are logged as warnings — a failed notification never crashes the bot.
    """
    url = _TELEGRAM_API.format(token=cfg.TELEGRAM_BOT_TOKEN)
    try:
        response = requests.post(
            url,
            json={
                "chat_id": cfg.TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("telegram_alert_failed", extra={"error": str(exc)})


def format_trade_alert(signal: TradingSignal, size_usdc: float, entry_price: float) -> str:
    """Format a trade signal as a human-readable Telegram message.

    Returns an HTML-safe string ready for send_alert().
    """
    side_icon = "🟢" if signal.side == "YES" else "🔴"
    question_short = signal.question[:80] + "…" if len(signal.question) > 80 else signal.question

    return (
        f"<b>{side_icon} NEW TRADE — {signal.side}</b>\n"
        f"📋 <i>{question_short}</i>\n"
        f"\n"
        f"📊 Edge: <b>{signal.edge_net:.1%}</b> | Conf: <b>{signal.confidence}/10</b>\n"
        f"💰 Size: <b>${size_usdc:.2f}</b> USDC @ {entry_price:.3f}\n"
        f"🤖 Agent: {signal.agent_probability:.1%} vs Market: {signal.market_probability:.1%}\n"
        f"🆔 <code>{signal.market_id}</code>\n"
        f"⏱ {signal.timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
    )


def format_scan_alert(
    markets_scanned: int,
    opportunities_found: int,
    trades_placed: int,
) -> str:
    """Format a cycle-end scan summary."""
    return (
        f"🔍 <b>Scan complete</b>\n"
        f"Markets: {markets_scanned} | Opportunities: {opportunities_found}"
        f" | Trades: {trades_placed}"
    )
