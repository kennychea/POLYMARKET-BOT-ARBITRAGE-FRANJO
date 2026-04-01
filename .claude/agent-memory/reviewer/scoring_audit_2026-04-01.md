---
name: scoring_audit_2026-04-01
description: Deep quantitative audit of core/scorer.py, core/calibration.py, core/resolver.py, infra/types.py, infra/config.py — scoring, edge calc, calibration, fee math
type: project
---

Audit performed on branch `Edouard` on 2026-04-01. 114 tests pass (test_fetcher, test_orchestrator, test_resolver). ruff found 8 violations in core/resolver.py only (0 in scorer.py, calibration.py, types.py, config.py).

## Critical bugs found

### 1. scorer.py:340-341 — Fee formula is wrong (most impactful)
Current:
```python
edge_yes = score.probability - market.yes_price - cfg.POLYMARKET_FEE
```
Bug: Subtracts a flat 0.02 from the probability gap. Polymarket's 2% fee applies to *profit*, not to the gap. The correct EV formula is:
```
edge_yes = agent_prob * (1 - market_price) * 0.98 - (1 - agent_prob) * market_price
```
At agent_prob=0.60, yes_price=0.50: current gives 0.08, correct gives 0.094 (understates by 18%). At yes_price=0.10: current gives 0.08, correct gives 0.0964 (understates by 17%). Direction and magnitude of error depend on price level — bot may reject valid low-probability trades.

### 2. scorer.py:393-430 — Divergence >0.15 has zero mechanical effect on trade gating
When second opinion diverges >0.15:
- Sets data_quality="low" (not used in tradeable gate)
- Keeps confidence unchanged (still fires if confidence >= MIN_CONFIDENCE)
- Uses first analyst's probability with no averaging
- data_quality is never checked in compute_edge or the tradeable condition
Fix: reduce confidence to below MIN_CONFIDENCE (e.g. set to 4) when opinions diverge >0.15, or return None from score_and_evaluate.

### 3. resolver.py:95-107 — calculate_pnl does not subtract 2% fee from winning trades
`pnl = size_shares * 1.0 - size_usdc` — no fee deduction. Paper bankroll systematically overstates returns by ~2% of profit on every won trade. Paper P&L cannot be compared to live account.

### 4. db.py:319 — SQL injection pattern suppressed with noqa:S608
`conn.execute(f"DELETE FROM trades WHERE id IN ({placeholders})", delete_ids)  # noqa: S608`
Placeholders are safe but pattern is wrong idiom. noqa masks a real warning category.

## High priority bugs

### 5. db.py:318-319 — paper_kelly_size uses wrong p
`p = market_price + edge` → actually computes `agent_prob - fee`, not true probability. Paper Kelly sizing is biased vs. live sizing in execution/sizing.py which uses correct agent_probability.

### 6. config.py:43 — INITIAL_BANKROLL_USDC=100.0 is hardcoded
`INITIAL_BANKROLL_USDC: float = 100.0  # manual update until wallet balance API`
If deployed with $500 bankroll and not updated, Kelly sizes are 5x too small. Must be an env var.

### 7. resolver.py:45-50 — fetch_market_resolution has no try/except at call site
Raises instead of returning None — inconsistent with project convention. json.JSONDecodeError indistinguishable from network error in upstream catch.

### 8. scorer.py:388-410 — confidence merge on agreement uses only first opinion's confidence
When agree (divergence ≤0.15): merged probability is averaged, but confidence = score.confidence (first analyst only). If first says confidence=8 and second says confidence=4, merged signal fires at confidence=8. Should use min(first.confidence, second.confidence).

## Medium issues

### 9. scorer.py:25-29 — Five module-level constants not in config
_MODEL, _MAX_TOKENS, _TEMPERATURE, _TIMEOUT, _MAX_RETRIES — all violate "no magic numbers outside config" rule in CLAUDE.md.

### 10. scorer.py:315, 392 — Divergence threshold 0.15 appears twice, not in config
Needs cfg.SECOND_OPINION_DIVERGENCE_THRESHOLD = 0.15

### 11. calibration.py:11,21,41 — Three magic numbers not in config
MIN_BUCKET_SAMPLES=10, clamp bounds 0.01/0.99, max_error=0.08

### 12. calibration.py:21 — Bias correction is linear (naive), no shrinkage
`adjusted = raw_prob + (bucket.actual_win_rate - bucket.predicted_prob)` — no shrinkage toward zero as count approaches MIN_BUCKET_SAMPLES. With 10-30 samples the correction is mostly noise. Should apply `alpha = min(1.0, count/50) * bias`.

### 13. scorer.py:203-205 — _extract_text has no bounds check on response.content
`block = response.content[0]` — IndexError if content is empty. Caught by bare except but logged as generic api_error.

### 14. config.py:45 — ENABLE_SECOND_OPINION=False hides the divergence-gating bug
Second opinion is disabled by default. Before enabling in live trading, fix items 2 and 8 first.

### 15. scorer.py:217 — getattr(market, "category", "default") should be market.category
MarketData now has category field (sprint 2). Defensive getattr suggests field may sometimes be absent. Needs explicit default in dataclass definition instead.

## ruff violations (resolver.py only)
- F401: `sys` imported but unused (line 14)
- I001: import block unsorted (line 10)
- F541: f-string without placeholders (lines 355, 372)
- E501: line too long (lines 263, 375, 382, 405)
All fixable with `ruff check --fix`.

## Test coverage gaps
- scorer.py: 0 dedicated unit tests. Missing: compute_edge (6 edge cases), _parse_scoring_response, score_and_evaluate divergence branch with ENABLE_SECOND_OPINION=True
- calibration.py: 0 dedicated unit tests. Missing: bucket boundary conditions, sub-threshold guard, is_calibrated with mixed buckets
- resolver.py: 19 tests, good coverage

## Priority fix order
1. scorer.py:340 — fix fee formula (Critical)
2. scorer.py:393 — divergence >0.15 must gate trade (Critical)
3. resolver.py:95 — deduct fee from winning PnL (High)
4. db.py:318 — fix paper_kelly_size p calculation (High)
5. config.py:43 — INITIAL_BANKROLL_USDC as env var (High)
6. scorer.py magic constants → config (Medium)
7. calibration.py magic constants + shrinkage (Medium)
8. scorer.py:203 — bounds check on response.content (Medium)
9. resolver.py ruff fixes (Low)

**Why:** Full quantitative audit of scoring/edge/calibration pipeline commissioned 2026-04-01.
**How to apply:** Use as PR checklist for any changes to scorer.py, calibration.py, resolver.py. Fee formula fix (item 1) and divergence gate fix (item 2) must ship together — they are independent bugs with potentially offsetting effects on trade frequency.
