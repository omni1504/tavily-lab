---
name: code-hygiene
description: Enforces linting, formatting, typing, testing and repo hygiene. Use whenever writing, editing, or refactoring code in this repo, and before declaring any task done.
---

# Code Hygiene

## Before writing code
- Read existing code nearby and match its patterns, naming and structure.
- For non-trivial work, state a short plan (files to touch, tests to add) first.
- Do not add a dependency without saying why; prefer the standard library.

## While writing code
- Small, single-purpose functions (< ~40 lines). No dead code, no commented-out code.
- Full type hints / strict types. No `any` / untyped public functions.
- No hardcoded secrets, URLs, or credentials — use config/env vars.
- Handle errors explicitly; never swallow exceptions silently.
- Docstrings/comments explain *why*, not *what*.
- No TODOs left behind unless the user agreed to them.

## Definition of done (run ALL, fix ALL failures)
Use the repo's `make` targets (or the equivalents below):

| Step      | Python                          | TypeScript                      |
|-----------|---------------------------------|---------------------------------|
| Format    | `ruff format .`                 | `npx prettier --write .`        |
| Lint      | `ruff check . --fix`            | `npx eslint . --max-warnings=0` |
| Types     | `mypy --strict src`             | `npx tsc --noEmit`              |
| Tests     | `pytest -q --cov=src --cov-fail-under=80` | `npx vitest run --coverage` |
| Security  | `bandit -r src -q` / `pip-audit` | `npm audit --audit-level=high` |

Rules:
- Never disable a lint rule, add `# noqa`, `# type: ignore`, `eslint-disable`, or skip a test to make checks pass. Fix the root cause; if truly impossible, stop and ask.
- Every new behavior gets a test; every bug fix gets a regression test.
- Do not report a task as complete until every check above passes. Paste the final check output in your summary.

## Commits
- Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).
- One logical change per commit. Never commit `.env`, build output, or large binaries.
