# TODO — Polymarket Agent

## In Progress
- [ ] pipeline/scheduler.py — APScheduler, 15min cycle

## Blocked
- [ ] core/calibration.py — needs 100+ signals
- [ ] dashboard/app.py — needs execution stable

## Missing tests
- [ ] tests/test_db.py
- [ ] tests/test_telegram.py

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
