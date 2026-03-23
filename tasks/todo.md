# TODO — Polymarket Agent

## In Progress
- [ ] core/news.py — Perplexity + RSS context (Edouard, after scorer)
- [ ] execution/sizing.py — Kelly fractional + circuit breaker (Franjo)
- [ ] execution/clob.py — CLOB limit order wrapper (Franjo, after sizing)

## Blocked
- [ ] pipeline/orchestrator.py — needs scorer + sizing + clob
- [ ] pipeline/scheduler.py — needs orchestrator
- [ ] core/calibration.py — needs 100+ signals
- [ ] dashboard/app.py — needs execution stable

## Missing tests
- [ ] tests/test_db.py
- [ ] tests/test_telegram.py

## Done
- [x] infra/config.py
- [x] infra/db.py
- [x] infra/types.py
- [x] infra/telegram.py
- [x] core/fetcher.py (35 tests green)
- [x] core/scorer.py — Claude API scoring + edge computation (15 tests green)
