---
name: implement
description: Implement a feature from a spec or description — plan, code, test, verify
argument-hint: "<feature description or path to spec file>"
allowed-tools: [Read, Write, Edit, Bash, Glob, Grep]
---

You are implementing: $ARGUMENTS

## Protocol

### Phase 1: Understand
1. Read `tasks/lessons.md` — apply all lessons
2. Read `tasks/todo.md` — check current state
3. If a spec exists in `.specs/`, read it. Otherwise, create a plan.
4. Read relevant skills in `.claude/skills/` for this task
5. Identify which files will be created or modified

### Phase 2: Plan
1. Write the implementation plan in `tasks/todo.md` under "In Progress"
2. List: files to create/modify, functions to implement, tests to write
3. Check `infra/types.py` — do existing contracts cover this, or do we need new ones?

### Phase 3: Implement
1. Write the code following `.claude/skills/project-conventions.md`
2. All thresholds from `infra/config.py`, structured logging, typed functions
3. Handle errors gracefully (try/except for external calls)
4. Write tests ALONGSIDE the code, not after

### Phase 4: Verify
1. Run `pytest tests/ -v --tb=short` — all tests must pass
2. Run `mypy --strict` on modified files
3. Run `ruff check` on modified files
4. If anything fails: fix it, don't skip it

### Phase 5: Document
1. Update `tasks/todo.md` — mark as done
2. If any lesson was learned: add to `tasks/lessons.md`
3. Summary: what was built, tests passing, files modified
