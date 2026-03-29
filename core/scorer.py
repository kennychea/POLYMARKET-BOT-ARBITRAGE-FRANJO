"""Claude API probability scoring engine + edge computation.

Entry point: score_and_evaluate(market, news_context) → TradingSignal | None
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

import infra.config as cfg
from core.fetcher import MarketData
from infra.types import EdgeResult, ScoringResult, TradingSignal

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1024
_TEMPERATURE = 0.0
_TIMEOUT = 30.0
_MAX_RETRIES = 1

_JSON_FORMAT_BLOCK = (
    'Respond ONLY in JSON, no markdown, no preamble:\n'
    "{\n"
    '  "probability": 0.XX,\n'
    '  "confidence": X,\n'
    '  "reasoning": "...",\n'
    '  "key_factors": ["...", "..."],\n'
    '  "bear_case": "...",\n'
    '  "bull_case": "...",\n'
    '  "data_quality": "high|medium|low"\n'
    "}"
)

_BASE_RULES = (
    "Rules:\n"
    "- Be calibrated: when you say 70%, it should happen ~70% of the time\n"
    "- Identify biases (availability, recency, anchoring to market price)\n"
    "- If insufficient data → confidence < 5, do not trade\n"
    "- NEVER anchor to the current market price — assess independently first\n"
)

SCORER_SYSTEM_PROMPT = (
    "You are an expert probability assessor for prediction markets.\n"
    "Your mission: estimate the TRUE probability (0.0 to 1.0) that an event resolves YES.\n"
    "\n" + _BASE_RULES + "\n" + _JSON_FORMAT_BLOCK
)

CATEGORY_PROMPTS: dict[str, str] = {
    "politics": (
        "You are an expert political analyst and probability assessor for prediction markets.\n"
        "Your mission: estimate the TRUE probability (0.0 to 1.0) that a political event resolves YES.\n"
        "\n"
        "Domain expertise:\n"
        "- Weigh polling data, sample sizes, and historical polling errors\n"
        "- Consider electoral history, incumbency advantage, and institutional dynamics\n"
        "- Account for partisan lean, demographic shifts, and turnout models\n"
        "- Watch for legislative procedural hurdles and veto points\n"
        "\n" + _BASE_RULES + "\n" + _JSON_FORMAT_BLOCK
    ),
    "science": (
        "You are an expert science analyst and probability assessor for prediction markets.\n"
        "Your mission: estimate the TRUE probability (0.0 to 1.0) that a scientific event resolves YES.\n"
        "\n"
        "Domain expertise:\n"
        "- Prioritize peer-reviewed publications and replication status\n"
        "- Assess scientific consensus vs. frontier claims critically\n"
        "- Consider R&D timelines, regulatory approval stages, and funding cycles\n"
        "- Distinguish incremental progress from breakthrough claims\n"
        "\n" + _BASE_RULES + "\n" + _JSON_FORMAT_BLOCK
    ),
    "sports_outcome": (
        "You are an expert sports analyst and probability assessor for prediction markets.\n"
        "Your mission: estimate the TRUE probability (0.0 to 1.0) that a sports outcome resolves YES.\n"
        "\n"
        "Domain expertise:\n"
        "- Analyze player/team statistics, recent form, and head-to-head records\n"
        "- Factor in injuries, suspensions, and roster changes\n"
        "- Cross-reference with bookmaker odds as a calibration anchor\n"
        "- Consider home/away advantage, schedule fatigue, and motivation\n"
        "\n" + _BASE_RULES + "\n" + _JSON_FORMAT_BLOCK
    ),
    "geopolitics": (
        "You are an expert geopolitical analyst and probability assessor for prediction markets.\n"
        "Your mission: estimate the TRUE probability (0.0 to 1.0) that a geopolitical event resolves YES.\n"
        "\n"
        "Domain expertise:\n"
        "- Analyze international relations, alliances, and power dynamics\n"
        "- Consider sanctions, treaties, and diplomatic precedents\n"
        "- Weigh historical analogies carefully — base rates of escalation vs. de-escalation\n"
        "- Account for domestic political incentives of key actors\n"
        "\n" + _BASE_RULES + "\n" + _JSON_FORMAT_BLOCK
    ),
}
CATEGORY_PROMPTS["default"] = SCORER_SYSTEM_PROMPT

def _build_second_opinion_prompt(first: ScoringResult) -> str:
    """Build the second-opinion system prompt with first analyst's results injected."""
    return (
        "You are reviewing another analyst's probability assessment for a prediction market.\n"
        "Your mission: independently estimate the TRUE probability (0.0 to 1.0) that the event resolves YES.\n"
        "\n"
        f"The first analyst estimated probability={first.probability:.2f} with confidence={first.confidence}/10.\n"
        f"Their reasoning: {first.reasoning}\n"
        "\n"
        "Your job:\n"
        "- Do NOT simply agree — look for blind spots, overlooked factors, or reasoning errors\n"
        "- If you agree, that is fine, but you must arrive there independently\n"
        "- Challenge assumptions and consider alternative scenarios\n"
        "\n" + _BASE_RULES + "\n" + _JSON_FORMAT_BLOCK
    )


def _build_user_message(market: MarketData, news_context: str) -> str:
    """Build the user message with market data and news context."""
    parts = [
        f"Question: {market.question}",
        f"Resolution date: {market.end_date.strftime('%Y-%m-%d')}",
        f"Current YES price: {market.yes_price:.2f}",
        f"Current NO price: {market.no_price:.2f}",
        f"Volume (USDC): {market.volume:,.0f}",
    ]
    if news_context:
        parts.append(f"\nRecent news context:\n{news_context}")
    return "\n".join(parts)


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences if present."""
    return re.sub(r"^```(?:json)?\s*\n?|\n?```\s*$", "", text.strip())


class ScorerResponse(BaseModel):
    """Pydantic model for validating Claude API scorer responses."""

    probability: float = Field(ge=0.0, le=1.0)
    confidence: int = Field(ge=0, le=10)
    reasoning: str = Field(min_length=10)
    key_factors: list[str] = Field(min_length=1)


def _parse_scoring_response(raw_text: str) -> ScoringResult | None:
    """Parse and validate Claude's JSON response into a ScoringResult."""
    cleaned = _strip_json_fences(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("scorer_invalid_json", extra={"raw": raw_text[:200]})
        return None

    try:
        validated = ScorerResponse.model_validate(data)
    except ValidationError as exc:
        logger.warning("scorer_validation_error", extra={"errors": str(exc)})
        return None

    return ScoringResult(
        probability=validated.probability,
        confidence=validated.confidence,
        reasoning=validated.reasoning,
        key_factors=validated.key_factors,
        bear_case=str(data.get("bear_case", "")),
        bull_case=str(data.get("bull_case", "")),
        data_quality=str(data.get("data_quality", "low")),
    )


def _call_claude(
    user_message: str, system_prompt: str = SCORER_SYSTEM_PROMPT,
) -> anthropic.types.Message | None:
    """Call Anthropic API and return full Message response (includes usage)."""
    client = anthropic.Anthropic(
        api_key=cfg.ANTHROPIC_API_KEY,
        timeout=_TIMEOUT,
    )
    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response


def _extract_text(response: anthropic.types.Message) -> str | None:
    """Extract text content from Anthropic Message response."""
    block = response.content[0]
    if block.type == "text":
        return block.text
    return None


def score_market(market: MarketData, news_context: str = "") -> ScoringResult | None:
    """Score a market by estimating true probability via Claude API.

    Selects a category-specific system prompt, calls the Anthropic API,
    parses the JSON response, and validates fields.
    Retries once on failure before returning None.
    """
    category = getattr(market, "category", "default")
    system_prompt = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["default"])
    logger.info(
        "scorer_prompt_selected",
        extra={"market_id": market.market_id, "category": category},
    )

    user_message = _build_user_message(market, news_context)
    attempts = 0

    while attempts <= _MAX_RETRIES:
        attempts += 1
        try:
            t0 = time.monotonic()
            response = _call_claude(user_message, system_prompt=system_prompt)
            elapsed = time.monotonic() - t0

            if response is None:
                logger.warning("scorer_empty_response", extra={"attempt": attempts})
                continue

            logger.info("scorer_api_call", extra={
                "market_id": market.market_id,
                "latency_ms": round(elapsed * 1000),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "model": _MODEL,
                "category": category,
            })

            raw_text = _extract_text(response)
            if raw_text is None:
                logger.warning("scorer_no_text_block", extra={"attempt": attempts})
                continue

            result = _parse_scoring_response(raw_text)
            if result is not None:
                return result
            logger.warning("scorer_parse_failed", extra={"attempt": attempts})
        except Exception:
            logger.warning("scorer_api_error", extra={"attempt": attempts}, exc_info=True)

    logger.warning(
        "scorer_all_attempts_failed",
        extra={"market_id": market.market_id, "question": market.question[:60]},
    )
    return None


def get_second_opinion(
    market: MarketData,
    news_context: str,
    first_result: ScoringResult,
) -> ScoringResult | None:
    """Call Claude a second time with a reviewer prompt to cross-check the first score.

    Returns a second ScoringResult, or None on failure.
    Logs a WARNING if the two probabilities diverge by more than 0.15.
    """
    system_prompt = _build_second_opinion_prompt(first_result)
    user_message = _build_user_message(market, news_context)

    try:
        t0 = time.monotonic()
        response = _call_claude(user_message, system_prompt=system_prompt)
        elapsed = time.monotonic() - t0

        if response is None:
            logger.warning("second_opinion_empty_response", extra={"market_id": market.market_id})
            return None

        logger.info("scorer_api_call", extra={
            "market_id": market.market_id,
            "latency_ms": round(elapsed * 1000),
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "model": _MODEL,
            "category": getattr(market, "category", "default"),
        })

        raw_text = _extract_text(response)
        if raw_text is None:
            logger.warning("second_opinion_no_text_block", extra={"market_id": market.market_id})
            return None
        result = _parse_scoring_response(raw_text)
        if result is None:
            logger.warning("second_opinion_parse_failed", extra={"market_id": market.market_id})
            return None

        divergence = abs(first_result.probability - result.probability)
        logger.info(
            "second_opinion_completed",
            extra={
                "market_id": market.market_id,
                "first_prob": first_result.probability,
                "second_prob": result.probability,
                "divergence": round(divergence, 4),
            },
        )
        if divergence > 0.15:
            logger.warning(
                "divergence_detected",
                extra={
                    "market_id": market.market_id,
                    "first_prob": first_result.probability,
                    "second_prob": result.probability,
                    "divergence": round(divergence, 4),
                },
            )
        return result
    except Exception:
        logger.warning(
            "second_opinion_api_error",
            extra={"market_id": market.market_id},
            exc_info=True,
        )
        return None


def compute_edge(score: ScoringResult, market: MarketData) -> EdgeResult:
    """Compute edge between agent probability and market price.

    Subtracts POLYMARKET_FEE from both sides and picks the best side.
    """
    edge_yes = score.probability - market.yes_price - cfg.POLYMARKET_FEE
    edge_no = (1.0 - score.probability) - market.no_price - cfg.POLYMARKET_FEE
    best_side: Literal["YES", "NO"] = "YES" if edge_yes > edge_no else "NO"
    edge_net = max(edge_yes, edge_no)
    tradeable = edge_net > cfg.MIN_EDGE_NET and score.confidence >= cfg.MIN_CONFIDENCE

    return EdgeResult(
        best_side=best_side,
        edge_yes=edge_yes,
        edge_no=edge_no,
        edge_net=edge_net,
        tradeable=tradeable,
    )


def build_trading_signal(
    market: MarketData,
    score: ScoringResult,
    edge: EdgeResult,
    news_context: str = "",
) -> TradingSignal:
    """Map market data, scoring result, and edge into a TradingSignal."""
    return TradingSignal(
        market_id=market.market_id,
        question=market.question,
        side=edge.best_side,
        agent_probability=score.probability,
        market_probability=market.yes_price,
        edge_net=edge.edge_net,
        confidence=score.confidence,
        tradeable=edge.tradeable,
        news_context=news_context,
        timestamp=datetime.now(UTC),
    )


def score_and_evaluate(
    market: MarketData, news_context: str = ""
) -> TradingSignal | None:
    """Main entry point: score a market and return a TradingSignal if tradeable.

    Called by pipeline/orchestrator.py every cycle.
    Returns None if scoring fails or market is not tradeable.
    """
    score = score_market(market, news_context)
    if score is None:
        return None

    if cfg.ENABLE_SECOND_OPINION:
        second = get_second_opinion(market, news_context, score)
        if second is not None:
            logger.info(
                "second_opinion_used",
                extra={
                    "market_id": market.market_id,
                    "first_prob": score.probability,
                    "second_prob": second.probability,
                },
            )

    edge = compute_edge(score, market)
    signal = build_trading_signal(market, score, edge, news_context)

    logger.info(
        "market_scored",
        extra={
            "market_id": market.market_id,
            "question": market.question[:60],
            "probability": score.probability,
            "confidence": score.confidence,
            "edge_net": round(edge.edge_net, 4),
            "tradeable": edge.tradeable,
            "best_side": edge.best_side,
        },
    )

    if not edge.tradeable:
        return None
    return signal


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Score a Polymarket market")
    parser.add_argument("--market-id", required=True, help="Condition ID of the market")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from core.fetcher import get_tradeable_markets

    markets = get_tradeable_markets()
    target = next((m for m in markets if m.market_id == args.market_id), None)
    if target is None:
        print(f"Market {args.market_id} not found in tradeable markets.")
        raise SystemExit(1)

    signal = score_and_evaluate(target)
    if signal:
        print(f"\nTradeable signal: {signal}")
    else:
        print("\nNo tradeable signal produced.")
