# Project Conventions

## Code style
- Python 3.11+, strict typing on all functions
- Dataclasses for domain objects (infra/types.py)
- No magic numbers — all thresholds in infra/config.py
- Secrets via .env + python-dotenv, loaded in config.py

## Logging
- Always structured: logger.info("event_name", extra={"key": value})
- Log levels: INFO for normal ops, WARNING for recoverable errors, ERROR for failures
- Never print() — always logger

## Error handling
- External calls (APIs, DB): try/except → return None or empty + log warning
- Never crash the bot — always degrade gracefully
- Retry once on transient errors (network, timeout), then give up

## Imports
- infra.types for all dataclasses (TradingSignal, Position, etc.)
- infra.config for all constants and secrets
- No cross-imports between core/ and execution/
- Dependency direction: core → infra ← execution

## Git
- Branch naming: feat/core-*, feat/exec-*, fix/*
- Commit format: "feat(core): description" or "fix(infra): description"
- PR to dev, never push to main directly
