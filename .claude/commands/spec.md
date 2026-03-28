---
name: spec
description: Interview me about a feature, then write a complete spec before coding
argument-hint: "<feature description>"
allowed-tools: [Read, Bash, Glob, Grep, Write]
---

You are designing a feature for a Polymarket trading bot. The feature is: $ARGUMENTS

Before writing ANY code:

1. Read CLAUDE.md and relevant skills in .claude/skills/
2. Interview me about this feature. Ask me ONE question at a time about:
   - Technical implementation details
   - Edge cases and error handling
   - How it integrates with existing modules (check infra/types.py contracts)
   - Tradeoffs and alternatives
   - Testing strategy
   Keep interviewing until all ambiguity is resolved.

3. Write a complete spec to `.specs/<feature-name>.md` with:
   - Overview (what + why)
   - API design (function signatures with types)
   - Data flow (inputs → outputs)
   - Edge cases + error handling
   - Test plan (specific test cases)
   - Integration points with existing modules

4. Tell me: "Spec written. Start a fresh session and run: claude --resume to execute it with clean context."

Do NOT write any code. This command is for planning only.
