# TODO — Polymarket Agent

## In Progress

## Done (recent)
- [x] pipeline/scheduler.py — APScheduler BackgroundScheduler, 15min cycle (10 tests green)

## Blocked
- [ ] core/calibration.py — needs 100+ signals

## Missing tests
- [x] tests/test_db.py (16 tests green)
- [x] tests/test_telegram.py (7 tests green)

## Done
- [x] infra/config.py
- [x] infra/db.py
- [x] infra/types.py (+ OrderResult)
- [x] infra/telegram.py
- [x] core/fetcher.py (35 tests green)
- [x] core/scorer.py — Claude API scoring + edge computation (15 tests green)
- [x] core/news.py — Perplexity + RSS news context aggregator (10 tests green)
- [x] pipeline/orchestrator.py — paper trading loop, fetcher→news→scorer (8 tests green)
- [x] execution/sizing.py — Kelly fractional + exposure checks + circuit breaker (17 tests green)
- [x] execution/clob.py — CLOB limit order wrapper + slippage protection (13 tests green)
- [x] execution/orders.py — fill tracking + stale cleanup + DB recording (13 tests green)
- [x] execution/portfolio.py — position management + resolution + health check (19 tests green)

## Claude Code Optimization (2026-03-28)
- [x] CLAUDE.md slimmed down (130 → ~90 lignes opérationnelles)
- [x] docs/architecture.md extracted (full architecture reference)
- [x] tasks/lessons.md populated with architectural decisions
- [x] Skills added: debugging.md, claude-api-patterns.md, streamlit-dashboard.md
- [x] Commands added: /test, /check, /status
- [x] Agents: reviewer enhanced with checklist, dashboard agent created
- [x] CI: .github/workflows/ci.yml (pytest + mypy + ruff)
- [x] dashboard/app.jsx — React dashboard complet (5 tabs, mock data, dark theme)
- [x] dashboard/api.py — FastAPI backend (4 endpoints, CORS, 9 tests green)
- [x] dashboard/app.jsx — wired to API with fallback to mock data
