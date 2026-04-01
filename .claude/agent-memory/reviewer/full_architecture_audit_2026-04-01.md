---
name: full_architecture_audit_2026-04-01
description: Full architecture, database, test coverage, and competitive audit across all layers — execution, scheduling, DB, types, tests
type: project
---

Comprehensive audit performed 2026-04-01 on branch `Edouard`. 230 tests pass (5 collection errors from missing py_clob_client / fastapi / apscheduler in venv — not test failures).

## Architecture

### Single Points of Failure
1. `run_single_cycle()` is synchronous and single-threaded. If Claude API hangs, the entire cycle stalls. No per-call timeout at the cycle level.
2. `track_order_fill()` polls for up to 300s inside the cycle — called from `record_fill` which is called synchronously after `place_limit_order`. This blocks the full cycle for 5 minutes per live order.
3. `portfolio_health_check()` is defined in `execution/portfolio.py` but is NEVER called from the orchestrator. The health gate is unused in the live code path.

### External Dependency Failure Handling
- Gamma API down: `get_tradeable_markets()` returns [], cycle completes with 0 markets. Graceful.
- Claude API timeout: `score_and_evaluate()` wrapped in try/except in orchestrator, returns None. Graceful.
- Perplexity API down: `build_news_context()` wrapped in try/except, returns "". Graceful.
- CLOB `place_limit_order()` exception: caught, returns OrderResult(status="error"). Graceful.
- CLOB `get_wallet_balance()` fails: falls back to `cfg.INITIAL_BANKROLL_USDC`. Dangerous if that value is wrong (see scoring audit).
- Telegram down: all send_alert() calls wrapped in try/except. Graceful.

### Idempotency (restart safety)
- Duplicate trade guard: `filter_already_traded()` prevents entering the same market twice per cycle.
- BUT the `cleanup_duplicate_trades()` function in `core/resolver.py` exists as a one-off CLI tool, suggesting duplicates have actually occurred.
- Paper bankroll is non-atomic (log_trade + update_paper_bankroll are separate transactions). Crash between them creates ghost trades.
- Live mode: `place_limit_order()` + `record_fill()` are sequential. If crash between them, the order is live on CLOB with no DB record. On restart, `cancel_stale_orders()` would cancel it after 60 min.

### Health Check / Heartbeat
- `portfolio_health_check()` exists but is NEVER invoked from the orchestrator. The circuit breaker IS called via `compute_position_size()` → `check_circuit_breaker()`, but health check with its composite `can_trade` flag and drawdown_pct diagnostics is dead code in the live path.
- No external heartbeat (no ping endpoint, no watchdog). Scheduler death is silent until Telegram alerts stop.

### Logging
- Structured logging with `extra={}` throughout — production quality.
- `cycle_complete` log includes duration_sec — good for latency monitoring.
- No correlation ID per cycle — if two cycles run (APScheduler overlap), logs are interleaved with no way to distinguish.
- `print()` used in `core/resolver.py` CLI functions (_print_summary, _print_bankroll, cleanup_duplicate_trades) — these are CLI helpers so acceptable but still violates convention.

### APScheduler Overlap (Critical Gap)
- `scheduler.add_job()` has no `max_instances=1`.
- If a cycle takes >900s (15 min), APScheduler fires a second cycle in parallel.
- Two cycles can simultaneously scan the same markets, score, and place orders on the same tokens.
- The `_lock = threading.Lock()` in scheduler.py protects the scheduler object, not the cycle execution.
- Fix: add `max_instances=1, coalesce=True` to `add_job()`.

### Track Order Fill Not Integrated
- `track_order_fill()` in `execution/orders.py` is tested but NEVER called by the orchestrator.
- The orchestrator calls `record_fill()` immediately after `place_limit_order()` without waiting for fill confirmation.
- This means trades are recorded as "open" in the DB without verifying they filled. Resolution cycle will never close them if they were rejected or expired.
- Net effect: DB can accumulate open positions that never actually filled on-chain.

## Database

### Schema
- Three tables: trades, market_scans, paper_bankroll.
- `trades` has a CHECK constraint on `side IN ('YES','NO')` and on `status`. Good.
- `paper_bankroll` has FOREIGN KEY referencing trades(id) — SQLite FK enforcement is off by default; `PRAGMA foreign_keys = ON` is never set.
- NO INDEXES on any column. `status='open'` filter, `resolution_date >= date(...)` range filter, and `market_id` dedup query all do full table scans. Fine for <10k trades but will degrade.

### Concurrency
- SQLite with WAL mode not enabled. Default journal mode (DELETE) serializes all writes.
- Two concurrent processes (e.g. scheduler + manual resolver run) will see `database is locked` errors. `_conn()` does not set `timeout=` on `sqlite3.connect()` — defaults to 5s. Lock contention silently returns errors.
- No WAL pragma, no timeout extension, no connection pool.

### Data Integrity
- FK not enforced (missing PRAGMA).
- `size_shares DEFAULT 0.0` and `order_id DEFAULT ''` are nullable sentinels, not NULL. Historical trades with these defaults cannot be distinguished from real zeros.
- No migration system — schema changes require manual ALTER TABLE or db recreation.
- Backup: `data/polymarket.db.bak-before-dedup` exists as a manual one-time backup. No automated backup.

## Test Coverage

### Counts
- 230 tests pass (ignoring 5 collection errors from missing deps).
- 5 test files cannot be collected: test_api.py (fastapi), test_clob.py, test_orders.py, test_portfolio.py, test_scheduler.py (all need py_clob_client/apscheduler).
- The 5 failing collection files cover ~50 tests that ARE written but cannot run.

### Coverage by module (estimated)
- infra/db.py: ~20 tests, excellent coverage (init, log_trade, update, calibration, paper_bankroll)
- execution/sizing.py: 17 tests, good coverage including circuit breaker and edge cases
- execution/orders.py: ~12 tests, good (cannot run due to missing dep)
- execution/portfolio.py: ~20 tests, good (cannot run due to missing dep)
- core/resolver.py: 19+12=31 tests, excellent
- core/scorer.py: ~30 tests, good
- pipeline/orchestrator.py: ~20+ tests
- pipeline/scheduler.py: cannot run

### Critical Paths NOT Tested
1. `track_order_fill()` called from orchestrator — never wired, so no integration test possible
2. `portfolio_health_check()` called from orchestrator — dead code, no test
3. `check_category_exposure()` called from `compute_position_size()` — dead code, no test
4. APScheduler `max_instances` overlap scenario — no test
5. Paper bankroll atomicity crash scenario — no test
6. CLOB `init_clob_client()` used twice in same cycle (once for orders, once for stale cleanup, once for resolution) — wasteful but not tested for error

### False Positive Risk
- `test_circuit_breaker_safe` and `test_circuit_breaker_triggered` create their own in-memory DB with actual resolved trades — testing real SQL. Not a false positive risk.
- `test_record_fill_success` mocks `log_trade` — tests the wiring but not the actual DB insert. Low risk.
- `TestResolverBankroll.test_resolution_updates_bankroll_on_win` tests end-to-end with real DB and only mocks the HTTP call. High confidence test.

## Competitive Assessment

### Where It Sits
This is a **paper-trading-first informational-edge bot** with a clean architecture but several pre-production gaps.

**Structural edges it has:**
- Multi-source news context (Perplexity + RSS) before each scoring call
- Claude API probability assessment with category-specific prompts
- Calibration layer (even if shrinkage is naive)
- Second-opinion gating (when enabled)
- Kelly fractional sizing with exposure caps

**Structural edges it lacks vs professional traders:**
1. No orderbook depth check — cannot verify there is enough liquidity at the quoted price
2. No fill confirmation — orders land in DB as "open" without verifying they actually filled
3. Circuit breaker is 7-day resolved PnL only — a single-cycle wipeout (5 simultaneous losses) is undetected for days
4. Fee formula is wrong (flat subtraction, not EV-adjusted) — systematically undervalues trades at non-50% prices
5. Divergence gate is silent — second opinion disagreement doesn't prevent trading
6. No market microstructure analysis (bid-ask spread, last traded time, order imbalance)
7. APScheduler overlap can double-trade the same markets
8. Category correlation is dead code — no actual correlation control

**What would need to change to go from hobby to systematic:**
1. Fix fee formula and divergence gating (scoring quality)
2. Wire `track_order_fill()` into the execution path (fill confirmation)
3. Wire `portfolio_health_check()` into the orchestrator (pre-cycle gate)
4. Add `max_instances=1` to APScheduler (overlap prevention)
5. Fix paper bankroll atomicity (log_trade + update_paper_bankroll in one transaction)
6. Add DB indexes on (status), (resolution_date), (market_id, side) (performance)
7. Enable SQLite WAL mode and set connection timeout (concurrency)
8. Enable `PRAGMA foreign_keys = ON` (integrity)
9. Move all magic numbers (AGGRESSIVE_OFFSET, MAX_SLIPPAGE, lookback_days, max_drawdown, max_exposure_pct) to infra/config.py
10. Fix INITIAL_BANKROLL_USDC as env var — hardcoded 100.0 will produce 5x undersized Kelly on a $500 bankroll

**Why relevant:** Full architectural gaps audit, 2026-04-01.
**How to apply:** Use as pre-live-trading checklist. Items 1-5 are blockers for live mode. Items 6-10 are required for systematic operation.
