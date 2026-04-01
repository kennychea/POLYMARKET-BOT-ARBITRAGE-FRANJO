---
name: pipeline_data_audit_2026-04-01
description: Data pipeline and orchestrator audit: config overrides bypass config.py, rate limiting inverted, APScheduler no max_instances, partial fetch discards data, paper bankroll non-atomic, no news cache
type: project
---

Audit of core/fetcher.py, core/news.py, pipeline/orchestrator.py, pipeline/scheduler.py, infra/db.py, infra/config.py on 2026-04-01.

**Why:** Full quantitative review of data flow from market fetch to trade decision.
**How to apply:** Use these findings as baseline when reviewing future pipeline changes.

## Critical Issues Found

1. **Config override bypasses infra/config.py** (fetcher.py:30-31, 373-376)
   - `_VOLUME_MAX_OVERRIDE = 500_000` and `_DAYS_MAX_OVERRIDE = 90` are hardcoded in fetcher.py
   - `config.MARKET_FILTERS["volume_max"]` (50_000) and `days_to_resolution[1]` (30) are never read
   - Violates project convention: all thresholds must be in infra/config.py

2. **Rate limiting inverted for Perplexity** (orchestrator.py:85-91)
   - `time.sleep(_NEWS_DELAY)` fires AFTER `build_news_context()` completes, not before the next call
   - For market 0: news fires immediately, no delay
   - For market 1: news fires immediately, THEN sleeps 1s between news and scorer
   - Result: consecutive Perplexity calls have zero deliberate spacing

3. **APScheduler no max_instances=1** (scheduler.py:54-61)
   - `add_job()` has no `max_instances=1` parameter
   - If a cycle exceeds 900s (15 min interval), APScheduler fires a second cycle in parallel
   - Two cycles can simultaneously scan, score, and execute against the same markets
   - misfire_grace_time=300 helps missed fires but does not prevent overlapping long cycles

4. **Paper trade non-atomic** (orchestrator.py:156-164)
   - `db.log_trade()` and `db.update_paper_bankroll()` are two separate SQLite transactions
   - Crash between lines 156 and 164 creates a trade in the DB without reducing bankroll
   - On restart: trade counted in open positions but bankroll is not reduced — overstated paper equity

## High Priority Issues

5. **Partial fetch failure discards page 0 data** (fetcher.py:108-119)
   - If page 1 or 2 raises RequestException, entire fetch returns []
   - Page 0 (100 markets) is discarded; correct behavior may be to cache partial results

6. **No news caching between cycles** (news.py: no cache mechanism)
   - Each call to `build_news_context()` makes a fresh Perplexity API call
   - Markets present in multiple consecutive cycles (TTL=5min, cycle=15min) pay the cost each time
   - Estimated cost per cycle: N_markets * ~$0.001 (sonar at 500 tokens)

7. **print() in CLI __main__ blocks** (fetcher.py:546-549, news.py:188)
   - Minor: only in `if __name__ == "__main__"` so not in production path, but violates convention

## Resolved / Good Findings

- mypy --strict: 0 errors across all 5 files
- ruff: 2 minor issues (import sort in fetcher.py, 1 line-too-long in orchestrator.py)
- Zero real API calls in tests; all mocked correctly
- Gamma API down: returns [] gracefully, no crash
- Cross-imports clean: core/ never imports execution/
- Secrets all from .env via config._require()
- 94/94 tests pass (35 fetcher, 59 orchestrator + fetcher-level)
- News parallelism correct: ThreadPoolExecutor runs Perplexity + RSS concurrently
- filter_already_traded: prevents double-entry on same market within a cycle
