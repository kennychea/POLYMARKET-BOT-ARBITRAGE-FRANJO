"""Shared domain types — interface contract between core and execution layers.

DO NOT MODIFY without PR + agreement from both owners (see CLAUDE.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


@dataclass
class TradingSignal:
    """Output of the scoring engine; input to the execution layer."""

    market_id: str
    question: str
    side: Literal["YES", "NO"]
    agent_probability: float       # 0.0–1.0
    market_probability: float      # current market price
    edge_net: float                # net edge after 2% fee
    confidence: int                # 0–10
    tradeable: bool
    news_context: str
    timestamp: datetime


@dataclass
class Position:
    """A live or resolved position tracked by portfolio.py."""

    position_id: str
    signal: TradingSignal
    entry_price: float
    size_usdc: float
    size_shares: float
    order_id: str
    status: Literal["open", "won", "lost", "void", "cancelled"]
    pnl: Optional[float]


@dataclass
class ScoringResult:
    """Output of Claude API probability assessment."""

    probability: float          # 0.0–1.0
    confidence: int             # 0–10
    reasoning: str
    key_factors: list[str]
    bear_case: str
    bull_case: str
    data_quality: str           # "high" | "medium" | "low"


@dataclass
class EdgeResult:
    """Computed edge between agent probability and market price."""

    best_side: Literal["YES", "NO"]
    edge_yes: float
    edge_no: float
    edge_net: float             # best edge after fees
    tradeable: bool


@dataclass
class CalibrationBucket:
    """Calibration stats for one probability bucket."""

    bucket_low: float
    bucket_high: float
    predicted_prob: float   # mean agent_probability in this bucket
    actual_win_rate: float  # actual wins / total in bucket
    count: int
    error: float            # |predicted_prob - actual_win_rate|
