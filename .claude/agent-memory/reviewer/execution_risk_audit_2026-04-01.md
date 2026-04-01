---
name: Execution and Risk Audit 2026-04-01
description: Deep quantitative audit of execution/, sizing/, clob/, portfolio/, db/ layers — Kelly formula, circuit breaker, slippage, correlation, PnL
type: project
---

Full audit of execution layer completed 2026-04-01. Key findings:

**Kelly Formula**
- Formula `(b*p - q) / b` is algebraically correct (equivalent to `p - q/b`)
- BUT `p = market_price + edge_net` underestimates true probability because `edge_net` already has fee deducted. Bias ~1% in probability space. Kelly sizes ~1-2% too small.
- Separate `paper_kelly_size()` in `infra/db.py` uses `max_pct=0.10` (10%) vs live `MAX_POSITION_PCT=0.08` (8%) — paper sizing is more aggressive than live, invalidating paper as a live proxy.

**Exposure / Risk**
- `check_category_exposure()` defined in `execution/sizing.py:59` is NEVER called in `compute_position_size()` or the orchestrator. Correlation control is dead code.
- Max total exposure is 40% (hardcoded in `sizing.py:76`, not in `infra/config.py`). 5 * 8% = 40%, so 5 simultaneous max-size positions are allowed even though total cap is also 40%.
- Worst-case simultaneous 5-loss = -$200 on $500 bankroll = 40% drawdown, which exceeds circuit breaker threshold of 20% in a single cycle before the 7-day window catches it.

**Circuit Breaker**
- Triggers only on 7-day resolved trade PnL. A single-cycle wipeout (all 5 positions lose) will not trigger it until those markets resolve, which can be days later.
- Fails open on DB error (`return True`), which is a documented and intentional design choice.
- No daily or intra-cycle loss limit.

**Magic Numbers**
- `AGGRESSIVE_OFFSET = 0.005`, `MAX_SLIPPAGE = 0.02` are module-level in `execution/clob.py:18-19`, not in `infra/config.py`.
- `max_exposure_pct=0.40`, `lookback_days=7`, `max_drawdown=0.20` are default parameters in `execution/sizing.py`, not in `infra/config.py`.

**Execution**
- All orders are GTC limit — correct.
- Limit price = `best_ask + 0.005`, slippage check against `best_ask * 1.02`. Correctly implemented.
- No orderbook depth check (size vs available liquidity). Could get partial fills silently.
- Partial fills: `track_order_fill()` treats `partial` as non-terminal (keeps polling) but the 5-minute timeout then cancels. The DB records the intended cost_usdc, not the actual filled amount.
- No cancel-replace logic — timeout cancels, no re-entry.

**Position Tracking / PnL**
- PnL formula `size_shares * 1.0 - size_usdc` is correct for binary markets.
- Fee not deducted on win PnL: when side wins, `pnl = size_shares - size_usdc`, but Polymarket charges 2% on gains. Actual pnl should be `size_shares - size_usdc - 0.02 * (size_shares - size_usdc)`. PnL overstated by ~2% of profit on wins.
- Resolution uses two separate code paths: `portfolio.py:calculate_pnl()` (execution layer) and `core/resolver.py:calculate_pnl()` (standalone). Both have the same fee omission bug.

**Tests**
- 36 tests, all pass. Tests properly mock API calls.
- No test for check_category_exposure being called (because it isn't called).
- No test for partial-fill DB recording discrepancy.

**Why relevant:** These bugs affect risk calculations, paper-to-live equivalence, and actual P&L accounting. Should be fixed before live deployment.

**How to apply:** Flag in any PR touching sizing.py, clob.py, portfolio.py, or resolver.py.
