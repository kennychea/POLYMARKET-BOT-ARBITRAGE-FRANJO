---
name: project_audit_2026-03-30
description: Full audit of core/, pipeline/, infra/db.py, infra/config.py, infra/types.py as of branch Edouard on 2026-03-30
type: project
---

Audit performed on branch `Edouard`. 206 tests pass (test_api.py excluded — fastapi not installed in venv). infra/models.py does NOT exist.

## core/ file readiness

### core/__init__.py
- Status: READY (single-line docstring, no logic)

### core/fetcher.py
- Status: PARTIAL (functional but two mypy hard errors on cache return paths)
- Returns: `list[MarketData]` from `get_tradeable_markets()`, `MarketData | None` from `parse_market()`, plain dicts from price/orderbook helpers
- Does NOT import from infra/types.py — defines its own `MarketData` dataclass locally (not a frozen contract type)
- No cross-imports from execution/

### core/scorer.py
- Status: PARTIAL — second opinion result is fetched but the `score` variable is NEVER updated; `compute_edge` always uses the first opinion only (dead code path, lines 381-390)
- Returns: `TradingSignal | None` from `score_and_evaluate()` (correct), `ScoringResult | None` from `score_market()` and `get_second_opinion()`
- Imports TradingSignal, ScoringResult, EdgeResult correctly from infra/types
- No cross-imports from execution/

### core/news.py
- Status: READY
- Returns: str from `build_news_context()`
- No cross-imports from execution/

### core/calibration.py
- Status: READY (functional, magic numbers not in config)
- Returns: float from `apply_calibration_adjustment()`, bool from `is_calibrated()`, dict from `get_calibration_report()`
- No cross-imports from execution/

## Known issues (updated 2026-03-30 after deep audit)

1. scorer.py:381-390 — second opinion result collected but `score` variable never updated; `compute_edge` always uses first opinion only. This is the primary logic gap.
2. fetcher.py:99 — `# type: ignore[return-value]` wrong error code AND actual `no-any-return` mypy error (2 mypy hard errors here)
3. fetcher.py:123 — same as above (2 more mypy hard errors)
4. core/calibration.py:11 — MIN_BUCKET_SAMPLES=10 is a magic number not in infra/config.py
5. core/calibration.py:22,42 — clamp values 0.01/0.99 and default max_error=0.08 not in config
6. core/scorer.py:307 — divergence threshold 0.15 is a magic number not in config
7. core/scorer.py:23-27 — _MODEL, _MAX_TOKENS, _TEMPERATURE, _TIMEOUT, _MAX_RETRIES are module-level constants, not in config (CLAUDE.md says all constants in config)
8. core/fetcher.py:22-24 — _PAGE_SIZE=100, _MAX_PAGES=3, _REQUEST_TIMEOUT=15 not in config
9. print() in __main__ blocks: fetcher.py:423-426, scorer.py:433-440, news.py:188 (minor — CLI only)
10. core/fetcher.py:92 — fetch_raw_markets() has no try/except; a network error propagates and can crash the cycle
11. core/news.py:152 — f-string in logger.warning("...") event name (should be literal string)
12. test_api.py — fastapi not installed in venv, collection always errors

## dashboard/ file readiness (audited 2026-03-30)

### dashboard/__init__.py
- Status: READY (single-line docstring, no logic)

### dashboard/api.py
- Status: READY (functional, all routes implemented, no stubs)
- Framework: FastAPI (not Streamlit — __init__.py docstring is misleading)
- Routes: GET /api/trades, /api/scans, /api/calibration, /api/health
- Imports: infra.config (cfg), infra.db — NO infra/types.py import (indirect via db.compute_calibration)
- No cross-imports from core/ or execution/
- Typing: partially typed — 4 mypy strict errors (untyped-decorator: FastAPI @app.get() routes)
- Ruff: clean (0 violations)
- Tests: 9/9 pass once fastapi installed (fastapi NOT in venv by default — must pip install)
- Known issue: fastapi/uvicorn declared in pyproject.toml but not installed in dev venv

### dashboard/ known issues
1. api.py:36,42,48,55 — 4 mypy --strict errors: "Untyped decorator makes function untyped [untyped-decorator]" (FastAPI @app.get decorators lack type stubs in mypy strict mode — needs fastapi-stubs or # type: ignore per route)
2. fastapi and uvicorn are in pyproject.toml dependencies but not installed in the dev venv — test_api.py always fails with ModuleNotFoundError unless manually installed
3. __init__.py docstring says "Streamlit P&L monitoring" but the actual implementation is FastAPI — documentation mismatch
4. db.init_db() called inside FastAPI lifespan but there is no error handling if the DB path is invalid or disk is full — crash at startup
5. CORS allow_origins is hardcoded inline (lines 30-33), not read from infra.config — minor magic-string violation

## infra/ file readiness (audited 2026-03-30)

### infra/__init__.py
- Status: READY (single-line docstring only)

### infra/types.py
- Status: READY (frozen contracts, fully typed, no stubs, no TODOs)
- Dataclasses: TradingSignal, Position, ScoringResult, EdgeResult, OrderResult, CalibrationBucket
- mypy --strict: PASS | ruff: PASS

### infra/config.py
- Status: READY (all secrets via _require(), all thresholds present)
- MARKET_FILTERS uses `dict[str, Any]` — acceptable for heterogeneous config dict
- Magic numbers: _REQUEST_TIMEOUT=10 in telegram.py NOT in config; _CALIBRATION_BUCKETS=10 in db.py NOT in config
- mypy --strict: PASS | ruff: PASS

### infra/db.py
- Status: READY (all DB functions implemented, no stubs, no TODOs)
- `# type: ignore[assignment]` on cursor.lastrowid (line 97): justified — sqlite3 stub types lastrowid as int|None but it is always int after a successful INSERT
- `_CALIBRATION_BUCKETS = 10` is a module-level magic number not in config (minor)
- `dict[str, Any]` return type on get_open_positions/get_all_trades/get_scans: acceptable (sqlite3.Row → dict is necessarily untyped)
- No retry on DB writes — connection errors propagate; callers do not catch (sqlite3 is local, so low risk, but worth noting)
- mypy --strict: PASS | ruff: PASS | 16/16 tests pass

### infra/telegram.py
- Status: READY (implemented, no stubs, no TODOs)
- `_REQUEST_TIMEOUT = 10` is a module-level magic number not in infra/config.py
- No retry on send_alert (convention requires retry(1) for external calls) — current behavior: fail silently on first error, which is acceptable for notifications
- Tests: all network calls mocked via `@patch("infra.telegram.requests.post")` — no real API calls
- mypy --strict: PASS | ruff: PASS | 7/7 tests pass

## infra/ known issues (2026-03-30)

1. telegram.py:14 — `_REQUEST_TIMEOUT = 10` is a magic number not in infra/config.py (violates "no magic numbers" rule)
2. db.py:17 — `_CALIBRATION_BUCKETS = 10` is a magic number not in infra/config.py
3. telegram.py — no retry on external POST (convention: retry(1)); currently fails silently which is acceptable for notifications but inconsistent with error-handling convention
4. db.py:97 — `# type: ignore[assignment]` present; justified (sqlite3 stub limitation) but should have an inline comment explaining why (currently has none)
5. telegram.py/db.py — `get_scans(limit=200)` default 200 is a magic number (minor)

## pipeline/ file readiness (audited 2026-03-30)

### pipeline/__init__.py
- Status: READY (single-line docstring, no logic)

### pipeline/orchestrator.py
- Status: PARTIAL (paper mode fully functional; live trading branch is an explicit logger.warning("live_mode_not_implemented") stub — no execution/)
- Functions: run_single_cycle(paper) -> dict[str, Any], run_loop(paper, interval) -> None
- Imports TradingSignal correctly from infra.types (line 20)
- No cross-imports from execution/ or dashboard/
- Typing: partially typed — dict[str, Any] return type on run_single_cycle (cannot be narrowed without a TypedDict)
- Ruff: 0 violations | mypy: 0 errors in pipeline/ (the 4 errors are in core/fetcher.py)
- Tests: 8/8 pass (test_orchestrator.py) — all external deps mocked

### pipeline/scheduler.py
- Status: READY (fully functional APScheduler wrapper)
- Functions: start(paper) -> BackgroundScheduler, stop() -> None, is_running() -> bool, _job_listener(event) -> None, _signal_handler(signum, _frame) -> None, main() -> None
- No cross-imports from execution/ or dashboard/
- Typing: fully typed (no Any, no type:ignore)
- Ruff: 0 violations | mypy: 0 errors
- Tests: 10/10 pass (test_scheduler.py) — all external deps mocked

## pipeline/ known issues (2026-03-30)

1. orchestrator.py:28 — return type dict[str, Any] is a high-priority warning; shape is stable (markets_scanned, opportunities, signals_sent, signals keys) — a TypedDict (e.g. CycleResult) would satisfy mypy --strict
2. orchestrator.py:24-25 — _NEWS_DELAY=1.0 and _SCORER_DELAY=0.5 are module-level constants not in infra/config.py (CLAUDE.md: all constants in config)
3. orchestrator.py:102-106 — live trading branch is a stub (logger.warning only); passing --live flag silently does nothing. No guard prevents --live from being used accidentally in production (should raise or exit if live trading not ready)
4. scheduler.py:51 — misfire_grace_time=300 hardcoded, not in infra/config
5. scheduler.py:32 — str(event.retval)[:200] uses magic number 200 for truncation, not in config
6. test_orchestrator.py:34,56 — # type: ignore[arg-type] on MarketData/TradingSignal constructors in test fixtures; acceptable in tests but worth noting

**Why:** Full audit of pipeline/ covering orchestrator.py and scheduler.py. Both ruff and mypy --strict pass cleanly. 18/18 pipeline tests pass. Core pipeline loop is functional in paper mode; live mode is explicitly stubbed out.
**How to apply:** Use as baseline when reviewing future PRs on branch Edouard — live-mode stub must be replaced or hard-guarded before live trading; dict[str, Any] return on run_single_cycle should be TypedDict for strict compliance. Magic number constants (_NEWS_DELAY, _SCORER_DELAY, misfire_grace_time) are the other open items.

## execution/ file readiness (audited 2026-03-30)

### execution/__init__.py
- Status: READY (single-line docstring, no logic)

### execution/clob.py
- Status: READY
- Functions: init_clob_client, get_best_price, compute_limit_price, place_limit_order, cancel_order, get_open_orders
- Imports from infra/types.py: OrderResult only
- No cross-imports from core/ or dashboard/
- Fully typed, ruff clean, mypy --strict passes
- Magic numbers not in config: CLOB_HOST, POLYGON_CHAIN_ID (137), AGGRESSIVE_OFFSET (0.005), MAX_SLIPPAGE (0.02)
- 13 tests pass, all mock ClobClient

### execution/orders.py
- Status: READY
- Functions: check_fill_status, track_order_fill, cancel_stale_orders, record_fill, _extract_order_id, _is_stale
- Imports from infra/types.py: OrderResult, TradingSignal
- No cross-imports from core/ or dashboard/
- Fully typed, ruff clean, mypy --strict passes
- Magic number defaults not in config: timeout_seconds=300, poll_interval=15, max_age_minutes=60
- 13 tests pass

### execution/sizing.py
- Status: READY
- Functions: kelly_size, check_exposure, check_category_exposure, check_total_exposure, check_circuit_breaker, compute_position_size
- Imports from infra/types.py: Position, TradingSignal
- Imports from infra/config.py: KELLY_FRACTION, MAX_POSITION_PCT, MAX_SIMULTANEOUS_POSITIONS, MIN_TRADE_SIZE (all correct)
- No cross-imports from core/ or dashboard/
- Fully typed, ruff clean, mypy --strict passes
- Magic number defaults not in config: max_per_category=2, max_exposure_pct=0.40, lookback_days=7, max_drawdown=0.20
- Circuit breaker cannot be programmatically bypassed; only fails open on DB error (by design, documented in docstring)
- 16 tests pass

### execution/portfolio.py
- Status: READY
- Functions: get_portfolio_snapshot, check_market_resolution, calculate_pnl, close_resolved_positions, portfolio_health_check, run_resolution_cycle, _rows_to_positions, _extract_category, _parse_outcome, _get_7d_pnl
- Imports from infra/types.py: Position, TradingSignal
- Imports from execution/sizing.py: check_circuit_breaker, check_total_exposure (intra-execution — OK)
- No cross-imports from core/ or dashboard/
- Fully typed, ruff clean, mypy --strict passes
- Known issues:
  1. portfolio.py:81 — raw requests.get() with no retry wrapper; single transient failure silently marks all positions as unresolved
  2. portfolio.py:21 — _REQUEST_TIMEOUT=10 magic number not in config
  3. portfolio.py:20 — _GAMMA_BASE URL hardcoded, not in config
  4. portfolio.py:35 — get_portfolio_snapshot(conn) accepts conn but never uses it — dead parameter
- 19 tests pass, requests.get mocked via patch

## execution/ known issues (priority order, 2026-03-30)

### High
1. portfolio.py:81 — no retry on requests.get(); missed resolutions possible on transient network errors
2. sizing.py + portfolio.py — ~8 magic number defaults not in infra/config.py
3. clob.py:15-18 — CLOB_HOST, POLYGON_CHAIN_ID, AGGRESSIVE_OFFSET, MAX_SLIPPAGE not in infra/config.py

### Medium
4. portfolio.py:28 — conn parameter is dead
5. orders.py:53,54,93 — timeout/poll_interval/max_age defaults not in config
6. portfolio.py:20 — _GAMMA_BASE hardcoded
