"""Claude API probability scoring engine + edge computation.

Entry point: score_and_evaluate(market, news_context) → TradingSignal | None
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import anthropic

import infra.config as cfg
from core.fetcher import MarketData
from infra.types import EdgeResult, ScoringResult, TradingSignal

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1024
_TEMPERATURE = 0.0
_TIMEOUT = 30.0
_MAX_RETRIES = 1

SCORER_SYSTEM_PROMPT = (
    "You are an expert probability assessor for prediction markets.\n"
    "Your mission: estimate the TRUE probability (0.0 to 1.0) that an event resolves YES.\n"
    "\n"
    "Rules:\n"
    "- Be calibrated: when you say 70%, it should happen ~70% of the time\n"
    "- Identify biases (availability, recency, anchoring to market price)\n"
    "- If insufficient data → confidence < 5, do not trade\n"
    "- NEVER anchor to the current market price — assess independently first\n"
    "\n"
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


def _parse_scoring_response(raw_text: str) -> ScoringResult | None:
    """Parse and validate Claude's JSON response into a ScoringResult."""
    cleaned = _strip_json_fences(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("scorer_invalid_json", extra={"raw": raw_text[:200]})
        return None

    prob = data.get("probability")
    conf = data.get("confidence")
    if prob is None or conf is None:
        logger.warning("scorer_missing_fields", extra={"keys": list(data.keys())})
        return None

    prob = float(prob)
    conf = int(conf)
    if not (0.0 <= prob <= 1.0):
        logger.warning("scorer_probability_out_of_range", extra={"probability": prob})
        return None
    if not (0 <= conf <= 10):
        logger.warning("scorer_confidence_out_of_range", extra={"confidence": conf})
        return None

    return ScoringResult(
        probability=prob,
        confidence=conf,
        reasoning=str(data.get("reasoning", "")),
        key_factors=list(data.get("key_factors", [])),
        bear_case=str(data.get("bear_case", "")),
        bull_case=str(data.get("bull_case", "")),
        data_quality=str(data.get("data_quality", "low")),
    )


def _call_claude(user_message: str) -> str | None:
    """Call Anthropic API and return raw text response. Returns None on failure."""
    client = anthropic.Anthropic(
        api_key=cfg.ANTHROPIC_API_KEY,
        timeout=_TIMEOUT,
    )
    response = client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        system=SCORER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    block = response.content[0]
    if block.type == "text":
        return block.text
    return None


def score_market(market: MarketData, news_context: str = "") -> ScoringResult | None:
    """Score a market by estimating true probability via Claude API.

    Calls the Anthropic API, parses the JSON response, and validates fields.
    Retries once on failure before returning None.
    """
    user_message = _build_user_message(market, news_context)
    attempts = 0

    while attempts <= _MAX_RETRIES:
        attempts += 1
        try:
            raw_text = _call_claude(user_message)
            if raw_text is None:
                logger.warning("scorer_empty_response", extra={"attempt": attempts})
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


def compute_edge(score: ScoringResult, market: MarketData) -> EdgeResult:
    """Compute edge between agent probability and market price.

    Subtracts POLYMARKET_FEE from both sides and picks the best side.
    """
    edge_yes = score.probability - market.yes_price - cfg.POLYMARKET_FEE
    edge_no = (1.0 - score.probability) - market.no_price - cfg.POLYMARKET_FEE
    best_side: str = "YES" if edge_yes > edge_no else "NO"
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
        timestamp=datetime.now(timezone.utc),
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
