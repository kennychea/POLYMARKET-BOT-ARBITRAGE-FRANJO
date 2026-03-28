---
name: fresh-start
description: Read this skill when starting a new coding session or resuming after a break
globs:
  - "**/*.py"
---

# Fresh Start Protocol

When starting a new session or resuming work:

1. Read `tasks/todo.md` — what's in progress?
2. Read `tasks/lessons.md` — what mistakes to avoid?
3. Run `pytest tests/ -v --tb=no -q` — what's the current test state?
4. Run `git status && git log --oneline -5` — what changed recently?
5. Check `.specs/` for any unimplemented specs

Then report:
- Current state (X tests passing, Y files modified)
- Next action from todo.md
- Any lessons that apply

Do NOT start coding until this checklist is complete.
