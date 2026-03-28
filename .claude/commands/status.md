---
name: status
description: Project status — git + tests + todo
allowed-tools: [Bash, Read]
---

Give a complete project status report:

1. **Git status:**
```bash
git status --short && echo "---" && git log --oneline -5
```

2. **Tests count:**
```bash
python -m pytest tests/ --tb=no -q 2>&1 | tail -3
```

3. **Todo:** Read `tasks/todo.md` and summarize what's in progress, done, and blocked.

4. **Lessons:** Read `tasks/lessons.md` and note the most recent lesson.

Report in this format:
- Branch: X, Y files modified, Z commits ahead
- Tests: X passed, Y failed
- In progress: [task]
- Next up: [task]
- Last lesson: [summary]
