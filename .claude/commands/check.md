---
name: check
description: Run full quality check — tests + mypy + ruff
allowed-tools: [Bash, Read]
---

Run the full quality pipeline in sequence. Stop and report on first failure:

1. **Tests:**
```bash
python -m pytest tests/ -v --tb=short 2>&1
```

2. **Type checking:**
```bash
python -m mypy core/ execution/ infra/ pipeline/ --strict 2>&1
```

3. **Linting:**
```bash
python -m ruff check core/ execution/ infra/ pipeline/ 2>&1
```

Report a summary:
- Tests: X/Y passed
- Mypy: clean or N errors
- Ruff: clean or N issues

Do NOT modify any code. This command is diagnostic only.
