---
name: test
description: Run all tests with coverage report
allowed-tools: [Bash, Read]
---

Run the full test suite and report results:

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

After running:
1. Report: X passed, Y failed, Z errors
2. If any test failed: show the failure details and suggest a fix
3. If all green: report the total count

Do NOT modify any code. This command is diagnostic only.
