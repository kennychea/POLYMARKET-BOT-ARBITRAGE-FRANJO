# Skills Index — Polymarket Agent

## Available Skills

| Skill | File | Use when |
|-------|------|----------|
| Polymarket API | polymarket-api.md | Working on core/fetcher.py, execution/clob.py, or any Polymarket API call |
| Scoring & Calibration | scoring-calibration.md | Working on core/scorer.py, core/calibration.py, or edge computation |
| Risk Management | risk-management.md | Working on execution/sizing.py, execution/portfolio.py, circuit breaker logic |
| Testing Patterns | testing-patterns.md | Writing or fixing any test in tests/ |
| Project Conventions | project-conventions.md | Any file — code style, logging, imports, git workflow |

## How to use
- Read the relevant skill BEFORE writing code in that area
- Multiple skills can apply (e.g. scorer.py → scoring-calibration + testing-patterns + project-conventions)
- Skills are reference docs, not runbooks — adapt to the specific task

## Architecture reminder
```
core/       → fetcher, scorer, news, calibration  (Owner: Edouard)
execution/  → sizing, clob, orders, portfolio     (Owner: Franjo)
infra/      → config, db, types, telegram          (Shared, PR review)
pipeline/   → orchestrator, scheduler              (After core stable)
dashboard/  → Streamlit app                        (After execution stable)
```

## Key contracts
- core/ and execution/ communicate ONLY via infra/types.py dataclasses
- All thresholds live in infra/config.py — never hardcode
- All secrets via .env — never in code or prompts
