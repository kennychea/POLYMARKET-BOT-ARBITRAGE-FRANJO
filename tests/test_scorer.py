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
    CATEGORY_PROMPTS,
    build_trading_signal,
    compute_edge,
    get_second_opinion,
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


def _mock_claude_response(
    text: str, input_tokens: int = 100, output_tokens: int = 50,
) -> MagicMock:
    """Create a mock Anthropic Message response with usage info."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    response = MagicMock()
    response.content = [block]
    response.usage = usage
    return response


# ── score_market tests ───────────────────────────────────────────────────────


@patch("core.scorer._call_claude")
def test_score_market_valid_json(mock_call: MagicMock) -> None:
    """Valid JSON response → returns ScoringResult with correct fields."""
    mock_call.return_value = _mock_claude_response(_valid_response_json(probability=0.72, confidence=8))
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
    mock_call.return_value = _mock_claude_response("this is not json at all")
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
    mock_call.return_value = _mock_claude_response(f"```json\n{inner}\n```")
    market = _make_market()

    result = score_market(market)

    assert result is not None
    assert result.probability == 0.55
    assert result.confidence == 6


@patch("core.scorer._call_claude")
def test_score_market_probability_out_of_range(mock_call: MagicMock) -> None:
    """Probability > 1.0 → returns None."""
    mock_call.return_value = _mock_claude_response(_valid_response_json(probability=1.5, confidence=7))
    market = _make_market()

    result = score_market(market)

    assert result is None


@patch("core.scorer._call_claude")
def test_score_market_confidence_out_of_range(mock_call: MagicMock) -> None:
    """Confidence > 10 → returns None."""
    mock_call.return_value = _mock_claude_response(_valid_response_json(probability=0.5, confidence=11))
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


# ── category prompt selection tests ─────────────────────────────────────────


@patch("core.scorer._call_claude")
def test_score_market_uses_politics_prompt(mock_call: MagicMock) -> None:
    """Politics category → _call_claude receives politics system prompt."""
    mock_call.return_value = _mock_claude_response(_valid_response_json())
    market = _make_market(category="politics")

    score_market(market)

    _, kwargs = mock_call.call_args
    assert kwargs["system_prompt"] == CATEGORY_PROMPTS["politics"]


@patch("core.scorer._call_claude")
def test_score_market_uses_science_prompt(mock_call: MagicMock) -> None:
    """Science category → _call_claude receives science system prompt."""
    mock_call.return_value = _mock_claude_response(_valid_response_json())
    market = _make_market(category="science")

    score_market(market)

    _, kwargs = mock_call.call_args
    assert kwargs["system_prompt"] == CATEGORY_PROMPTS["science"]


@patch("core.scorer._call_claude")
def test_score_market_unknown_category_uses_default(mock_call: MagicMock) -> None:
    """Unknown category → falls back to default prompt."""
    mock_call.return_value = _mock_claude_response(_valid_response_json())
    market = _make_market(category="unknown_thing")

    score_market(market)

    _, kwargs = mock_call.call_args
    assert kwargs["system_prompt"] == CATEGORY_PROMPTS["default"]


# ── get_second_opinion tests ────────────────────────────────────────────────


@patch("core.scorer._call_claude")
def test_second_opinion_returns_result(mock_call: MagicMock) -> None:
    """Second opinion with valid response → returns ScoringResult."""
    mock_call.return_value = _mock_claude_response(_valid_response_json(probability=0.60, confidence=7))
    market = _make_market()
    first = ScoringResult(
        probability=0.65, confidence=7,
        reasoning="Strong case", key_factors=["a"], bear_case="b", bull_case="c",
        data_quality="high",
    )

    result = get_second_opinion(market, "news", first)

    assert result is not None
    assert result.probability == 0.60


@patch("core.scorer._call_claude")
def test_second_opinion_divergence_warning(mock_call: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """Divergence > 0.15 → logs WARNING 'divergence_detected'."""
    mock_call.return_value = _mock_claude_response(_valid_response_json(probability=0.40, confidence=6))
    market = _make_market()
    first = ScoringResult(
        probability=0.70, confidence=8,
        reasoning="High", key_factors=["x"], bear_case="", bull_case="",
        data_quality="high",
    )

    import logging
    with caplog.at_level(logging.WARNING):
        result = get_second_opinion(market, "news", first)

    assert result is not None
    assert any("divergence_detected" in r.message for r in caplog.records)


@patch("core.scorer._call_claude")
def test_second_opinion_no_divergence_no_warning(mock_call: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """Divergence <= 0.15 → no WARNING logged."""
    mock_call.return_value = _mock_claude_response(_valid_response_json(probability=0.63, confidence=7))
    market = _make_market()
    first = ScoringResult(
        probability=0.65, confidence=7,
        reasoning="Close", key_factors=["a"], bear_case="", bull_case="",
        data_quality="high",
    )

    import logging
    with caplog.at_level(logging.WARNING):
        get_second_opinion(market, "news", first)

    assert not any("divergence_detected" in r.message for r in caplog.records)


@patch("core.scorer._call_claude")
def test_second_opinion_api_failure_returns_none(mock_call: MagicMock) -> None:
    """API exception in second opinion → returns None."""
    mock_call.side_effect = Exception("timeout")
    market = _make_market()
    first = ScoringResult(
        probability=0.65, confidence=7,
        reasoning="", key_factors=[], bear_case="", bull_case="",
        data_quality="high",
    )

    result = get_second_opinion(market, "", first)

    assert result is None


# ── score_and_evaluate with second opinion ──────────────────────────────────


@patch("core.scorer.get_second_opinion")
@patch("core.scorer.score_market")
def test_score_and_evaluate_calls_second_opinion_when_enabled(
    mock_score: MagicMock, mock_second: MagicMock
) -> None:
    """ENABLE_SECOND_OPINION=True → get_second_opinion is called."""
    mock_score.return_value = ScoringResult(
        probability=0.70, confidence=8,
        reasoning="High edge", key_factors=["x"], bear_case="b", bull_case="c",
        data_quality="high",
    )
    mock_second.return_value = ScoringResult(
        probability=0.68, confidence=7,
        reasoning="Confirmed", key_factors=["y"], bear_case="", bull_case="",
        data_quality="high",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    with patch("core.scorer.cfg.ENABLE_SECOND_OPINION", True):
        signal = score_and_evaluate(market, news_context="news")

    assert signal is not None
    mock_second.assert_called_once()


@patch("core.scorer.get_second_opinion")
@patch("core.scorer.score_market")
def test_score_and_evaluate_skips_second_opinion_when_disabled(
    mock_score: MagicMock, mock_second: MagicMock
) -> None:
    """ENABLE_SECOND_OPINION=False → get_second_opinion is NOT called."""
    mock_score.return_value = ScoringResult(
        probability=0.70, confidence=8,
        reasoning="High edge", key_factors=["x"], bear_case="b", bull_case="c",
        data_quality="high",
    )
    market = _make_market(yes_price=0.50, no_price=0.50)

    with patch("core.scorer.cfg.ENABLE_SECOND_OPINION", False):
        signal = score_and_evaluate(market, news_context="news")

    assert signal is not None
    mock_second.assert_not_called()


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


# ── Prompt 6 — additional coverage ─────────────────────────────────────────


def test_category_prompts_has_all_expected_keys() -> None:
    """CATEGORY_PROMPTS must contain all expected categories + default."""
    expected = {"politics", "science", "sports_outcome", "geopolitics", "default"}
    assert expected.issubset(CATEGORY_PROMPTS.keys())
    for key in expected:
        assert len(CATEGORY_PROMPTS[key]) > 50, f"Prompt for {key} is suspiciously short"


@patch("core.scorer._call_claude")
def test_score_market_pydantic_missing_field_returns_none(mock_call: MagicMock) -> None:
    """Missing required Pydantic field (key_factors) → returns None."""
    incomplete = json.dumps({
        "probability": 0.65,
        "confidence": 7,
        "reasoning": "Solid analysis here.",
        # key_factors missing
    })
    mock_call.return_value = _mock_claude_response(incomplete)
    market = _make_market()

    result = score_market(market)

    assert result is None


@patch("core.scorer._call_claude")
def test_score_market_pydantic_short_reasoning_returns_none(mock_call: MagicMock) -> None:
    """Reasoning too short (< 10 chars) → Pydantic validation fails → None."""
    bad = json.dumps({
        "probability": 0.65,
        "confidence": 7,
        "reasoning": "Short",
        "key_factors": ["a"],
    })
    mock_call.return_value = _mock_claude_response(bad)
    market = _make_market()

    result = score_market(market)

    assert result is None


@patch("core.scorer._call_claude")
def test_score_market_logs_latency_and_tokens(
    mock_call: MagicMock, caplog: pytest.LogCaptureFixture,
) -> None:
    """scorer_api_call log must contain latency_ms, input_tokens, output_tokens."""
    mock_call.return_value = _mock_claude_response(
        _valid_response_json(), input_tokens=200, output_tokens=80,
    )
    market = _make_market()

    import logging
    with caplog.at_level(logging.INFO):
        score_market(market)

    api_records = [r for r in caplog.records if r.message == "scorer_api_call"]
    assert len(api_records) >= 1
    extra = api_records[0].__dict__
    assert "latency_ms" in extra
    assert extra["input_tokens"] == 200
    assert extra["output_tokens"] == 80
    assert extra["model"] == "claude-sonnet-4-20250514"
