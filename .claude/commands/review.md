---
name: review
description: Review code changes since last commit — find issues before PR
allowed-tools: [Bash, Read, Glob, Grep]
---

You are doing a pre-PR code review. Read `.claude/agents/reviewer.md` for the full checklist.

Steps:
1. Run `git diff --name-only` to see changed files
2. Run `git diff` to see all changes
3. For each changed file, apply the reviewer checklist (Critical → High → Medium)
4. Run `ruff check` on changed files
5. Run `mypy --strict` on changed files
6. Run `pytest tests/ -v --tb=short`

Output format:
```
## Changed files
- file1.py (+X/-Y lines)

## Critical Issues
- [file:line] description

## Warnings
- [file:line] description

## Quality Gates
- Ruff: ✅/❌
- Mypy: ✅/❌
- Tests: X passed / Y failed

## Verdict: READY / NOT READY for PR
```

Do NOT modify any code. This command is diagnostic only.
