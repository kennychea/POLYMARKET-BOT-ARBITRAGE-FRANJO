# Reviewer Agent Memory Index

- [user_profile.md](user_profile.md) — Developer role, trading bot context, review preferences
- [project_audit_2026-03-30.md](project_audit_2026-03-30.md) — First full core/pipeline/infra audit: known issues, ready files, stubs
- [scoring_audit_2026-04-01.md](scoring_audit_2026-04-01.md) — Deep quantitative audit of scorer/edge/calibration/resolver: fee formula wrong, divergence gate silent, PnL overstated, paper Kelly biased
- [execution_risk_audit_2026-04-01.md](execution_risk_audit_2026-04-01.md) — Execution/risk audit: category correlation dead code, circuit breaker timing gap, partial fill PnL mismatch, fee missing from win PnL, magic numbers not in config
- [pipeline_data_audit_2026-04-01.md](pipeline_data_audit_2026-04-01.md) — Data pipeline audit: config overrides bypass config.py, rate limiting inverted, APScheduler no max_instances, paper bankroll non-atomic
- [full_architecture_audit_2026-04-01.md](full_architecture_audit_2026-04-01.md) — Full architecture/DB/test/competitive audit: track_order_fill unwired, health check dead, no APScheduler overlap guard, no DB indexes, 5 test collection errors

Notes:
- Agent threads always have their cwd reset between bash calls, as a result please only use absolute file paths.
- In your final response, share file paths (always absolute, never relative) that are relevant to the task. Include code snippets only when the exact text is load-bearing (e.g., a bug you found, a function signature the caller asked for) — do not recap code you merely read.
- For clear communication with the user the assistant MUST avoid using emojis.
- Do not use a colon before tool calls. Text like "Let me read the file:" followed by a read tool call should just be "Let me read the file." with a period.
