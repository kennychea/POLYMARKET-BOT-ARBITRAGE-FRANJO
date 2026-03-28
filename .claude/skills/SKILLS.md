# Skills Index

| Skill | File | Use When |
|-------|------|----------|
| Polymarket API | polymarket-api.md | core/fetcher.py, execution/clob.py, Gamma/CLOB calls |
| Scoring & Calibration | scoring-calibration.md | core/scorer.py, edge computation |
| Claude API Patterns | claude-api-patterns.md | Anthropic API calls, prompt engineering, JSON parsing, retry logic |
| Risk Management | risk-management.md | execution/sizing.py, portfolio.py, circuit breaker |
| Testing Patterns | testing-patterns.md | Any test in tests/ |
| Project Conventions | project-conventions.md | All files — style, logging, imports, git |
| Debugging Protocol | debugging.md | Bug reports, failing tests, production issues |
| Streamlit Dashboard | streamlit-dashboard.md | dashboard/app.py, data visualization, monitoring UI |
| Fresh Start | fresh-start/SKILL.md | Beginning of every coding session |

## Architecture Reminder

```
core/       → fetcher, scorer, news, calibration  (Owner: Edouard)
execution/  → sizing, clob, orders, portfolio     (Owner: Franjo)
infra/      → config, db, types, telegram          (Shared, PR review)
pipeline/   → orchestrator, scheduler              (After core stable)
dashboard/  → Streamlit app                        (After execution stable)
```

## Key Contracts
- core/ and execution/ communicate ONLY via infra/types.py dataclasses
- All thresholds live in infra/config.py (never hardcode)
- All secrets via .env (never in code)
- Dependency direction: core/ → infra/ ← execution/

## Agents

| Agent | Domain | Model |
|-------|--------|-------|
| data-pipeline | core/fetcher.py, core/news.py | Sonnet |
| scorer | core/scorer.py, core/calibration.py | Opus |
| executor | execution/* | Sonnet |
| infra | infra/* | Sonnet |
| reviewer | Code audit (read-only) | Sonnet |
| tester | tests/* | Sonnet |
| dashboard | dashboard/* | Sonnet |

## Commands

| Command | Description |
|---------|-------------|
| /test | Run full test suite |
| /check | Tests + mypy + ruff |
| /status | Git + tests + todo summary |
| /spec | Design a feature spec before coding |
| /review | Pre-PR code review with quality gates |
| /fix | Auto-fix ruff and mypy issues |
| /implement | Full implementation cycle: plan → code → test → verify |
