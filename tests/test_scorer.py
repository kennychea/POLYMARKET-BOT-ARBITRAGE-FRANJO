"""Tests for core/scorer.py — Claude API probability scoring engine.

All Anthropic API calls are mocked. Zero real API calls.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.fetcher import MarketData
from core.scorer import (
    build_trading_signal,
    compute_edge,
    score_and_evaluate,
    score_market,
)
from infra.types import EdgeResult, ScoringResult


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_market(**overrides: object) -> MarketData:
    """Create a MarketData instance with sensible defaults."""
    defaults = dict(
        market_id="0xabc123",
        question="Will X happen by 2026-06-01?",
        yes_price=0.50,
        no_price=0.50,
        spread=0.02,
        volume=10_000.0,
        days_to_resolution=14.0,
        end_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category="politics",
        tags=["politics"],
    )
    defaults.update(overrides)
    return MarketData(**defaults)  # type: ignore[arg-type]


def _valid_response_json(
    probability: float = 0.65,
    confidence: int = 7,
) -> str:
    """Build a valid scorer JSON response."""
    return json.dumps({
        "probability": probability,
        "confidence": confidence,
        "reasoning": "Strong indicators point to YES.",
        "key_factors": ["factor_a", "factor_b"],
        "bear_case": "Unexpected reversal.",
        "bull_case": "Trend continues.",
        "data_quality": "high",
    })


def _mock_anthropic_response(text: str) -> MagicMock:
    """Create a mock Anthropic messages.create() response."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


# ── score_market tests ───────────────────────────────────────────────────────


@patch("core.scorer._call_claude")
def test_score_market_valid_json(mock_call: MagicMock) -> None:
    """Valid JSON response → returns ScoringResult with correct fields."""
    mock_call.return_value = _valid_response_json(probability=0.72, confidence=8)
    market = _make_market()

    result = score_market(market, news_context="Some news")

    assert result is not None
    assert result.probability == 0.72
    assert result.confidence == 8
    assert result.reasoning == "Strong indicators point to YES."
    assert result.key_factors == ["factor_a", "factor_b"]
    assert result.data_quality == "high"


@patch("core.scorer._call_claude")
def test_score_market_invalid_json(mock_call: MagicMock) -> None:
    """Invalid JSON → returns None."""
    mock_call.return_value = "this is not json at all"
    market = _make_market()

    result = score_market(market)

    assert result is None


@patch("core.scorer._call_claude")
def test_score_market_api_exception_retries(mock_call: MagicMock) -> None:
    """API exception → retries once, then returns None."""
    mock_call.side_effect = Exception("API timeout")
    market = _make_market()

    result = score_market(market)

    assert result is None
    assert mock_call.call_count == 2  # initial + 1 retry


@patch("core.scorer._call_claude")
def test_score_market_strips_json_fences(mock_call: MagicMock) -> None:
    """Response wrapped in ```json fences → strips and parses correctly."""
    inner = _valid_response_json(probability=0.55, confidence=6)
    mock_call.return_value = f"```json\n{inner}\n```"
    market = _make_market()

    result = score_market(market)

    assert result is not None
    assert result.probability == 0.55
    assert result.confidence == 6


@patch("core.scorer._call_claude")
def test_score_market_probability_out_of_range(mock_call: MagicMock) -> None:
    """Probability > 1.0 → returns None."""
    mock_call.return_value = _valid_response_json(probability=1.5, confidence=7)
    market = _make_market()

    result = score_market(market)

    assert result is None


@patch("core.scorer._call_claude")
def test_score_market_confidence_out_of_range(mock_call: MagicMock) -> None:
    """Confidence > 10 → returns None."""
    mock_call.return_value = _valid_response_json(probability=0.5, confidence=11)
    market = _make_market()

    result = score_market(market)

    assert result is None


@patch("core.scorer._call_claude")
def test_score_market_empty_response(mock_call: MagicMock) -> None:
    """Empty response from API → retries, then returns None."""
    mock_call.return_value = None
    market = _make_market()

    result = score_market(market)

    assert result is None
    assert mock_call.call_count == 2


# ── compute_edge tests ───────────────────────────────────────────────────────


def test_compute_edge_tradeable() -> None:
    """agent_prob=0.65, market_yes=0.50 → edge_yes=0.13, after fees=0.11, tradeable."""
    score = ScoringResult(
        probability=0.65, confidence=7,
        reasoning="", key_factors=[], bear_case="", bull_case="",
        data_quality="high",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    edge = compute_edge(score, market)

    assert edge.edge_yes == pytest.approx(0.13)
    assert edge.edge_net == pytest.approx(0.13)
    assert edge.best_side == "YES"
    assert edge.tradeable is True


def test_compute_edge_no_edge() -> None:
    """agent_prob=0.52, market_yes=0.50 → edge_net=0.00, not tradeable."""
    score = ScoringResult(
        probability=0.52, confidence=7,
        reasoning="", key_factors=[], bear_case="", bull_case="",
        data_quality="medium",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    edge = compute_edge(score, market)

    assert edge.edge_net == pytest.approx(0.00)
    assert edge.tradeable is False


def test_compute_edge_no_side() -> None:
    """agent_prob=0.30, market_yes=0.50 → best_side='NO'."""
    score = ScoringResult(
        probability=0.30, confidence=8,
        reasoning="", key_factors=[], bear_case="", bull_case="",
        data_quality="high",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    edge = compute_edge(score, market)

    assert edge.best_side == "NO"
    # edge_no = (1.0 - 0.30) - 0.50 - 0.02 = 0.18
    assert edge.edge_no == pytest.approx(0.18)
    assert edge.edge_net == pytest.approx(0.18)
    assert edge.tradeable is True


def test_compute_edge_low_confidence_not_tradeable() -> None:
    """confidence=5 with edge > 0.05 → not tradeable (MIN_CONFIDENCE is 6)."""
    score = ScoringResult(
        probability=0.70, confidence=5,
        reasoning="", key_factors=[], bear_case="", bull_case="",
        data_quality="low",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    edge = compute_edge(score, market)

    # edge_yes = 0.70 - 0.50 - 0.02 = 0.18 > MIN_EDGE_NET
    assert edge.edge_net == pytest.approx(0.18)
    # But confidence=5 < MIN_CONFIDENCE=6 → not tradeable
    assert edge.tradeable is False


# ── build_trading_signal tests ───────────────────────────────────────────────


def test_build_trading_signal_maps_fields() -> None:
    """All fields correctly mapped from market + score + edge."""
    market = _make_market(market_id="0xdef456", question="Will Y happen?", yes_price=0.40)
    score = ScoringResult(
        probability=0.60, confidence=8,
        reasoning="Strong case", key_factors=["a"], bear_case="b", bull_case="c",
        data_quality="high",
    )
    edge = EdgeResult(
        best_side="YES", edge_yes=0.18, edge_no=-0.02,
        edge_net=0.18, tradeable=True,
    )

    signal = build_trading_signal(market, score, edge, news_context="ctx")

    assert signal.market_id == "0xdef456"
    assert signal.question == "Will Y happen?"
    assert signal.side == "YES"
    assert signal.agent_probability == 0.60
    assert signal.market_probability == 0.40
    assert signal.edge_net == 0.18
    assert signal.confidence == 8
    assert signal.tradeable is True
    assert signal.news_context == "ctx"
    assert isinstance(signal.timestamp, datetime)


# ── score_and_evaluate tests ─────────────────────────────────────────────────


@patch("core.scorer.score_market")
def test_score_and_evaluate_tradeable(mock_score: MagicMock) -> None:
    """Tradeable signal → returns TradingSignal."""
    mock_score.return_value = ScoringResult(
        probability=0.70, confidence=8,
        reasoning="High edge", key_factors=["x"], bear_case="b", bull_case="c",
        data_quality="high",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    signal = score_and_evaluate(market, news_context="news")

    assert signal is not None
    assert signal.tradeable is True
    assert signal.side == "YES"
    assert signal.agent_probability == 0.70


@patch("core.scorer.score_market")
def test_score_and_evaluate_not_tradeable(mock_score: MagicMock) -> None:
    """Not tradeable → returns None."""
    mock_score.return_value = ScoringResult(
        probability=0.52, confidence=7,
        reasoning="Marginal", key_factors=[], bear_case="", bull_case="",
        data_quality="medium",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    signal = score_and_evaluate(market)

    assert signal is None


@patch("core.scorer.score_market")
def test_score_and_evaluate_score_fails(mock_score: MagicMock) -> None:
    """score_market returns None → score_and_evaluate returns None."""
    mock_score.return_value = None
    market = _make_market()

    signal = score_and_evaluate(market)

    assert signal is None
