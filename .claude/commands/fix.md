---
name: fix
description: Auto-fix ruff and mypy issues across the project
argument-hint: "<optional: specific file or module to fix>"
allowed-tools: [Bash, Read, Write, Edit, Glob, Grep]
---

Fix code quality issues. Target: $ARGUMENTS (or all modules if empty).

Steps:
1. Run `ruff check --fix core/ execution/ infra/ pipeline/` to auto-fix what ruff can
2. Run `ruff check core/ execution/ infra/ pipeline/` to see remaining issues
3. For each remaining ruff issue: fix manually
4. Run `mypy core/ execution/ infra/ pipeline/ --strict` to find type errors
5. For each mypy error: fix the type annotation or add proper typing
6. Run `pytest tests/ -v --tb=short` to verify nothing broke
7. Report what was fixed

Rules:
- Never suppress warnings with `# noqa` or `# type: ignore` without justification
- Never change logic to fix a type error — fix the types
- If a test breaks after fixing: the fix was wrong, revert it
- Always run the full test suite after all fixes
