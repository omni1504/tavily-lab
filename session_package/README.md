# Session package

This folder holds the artifacts from the Claude Code session `9ded8427-f5c3-41bd-a29a-9e2affa1885a`, in which the Tavily-Lab features were built (2026-11-13).

| Path | Contents |
|---|---|
| `technical_statement.md` | The Sales-O-Matic solution brief (hand-written). |
| `dev_session_log.zip` | The sanitized session logs: `samples/session.jsonl` (raw log) and `samples/session.md` (the same log rendered with `parser/parse_session.py`). API keys, the AWS profile name and the work email are redacted. Unzip it here; the extracted `samples/` folder is git-ignored. |
| `agent/CLAUDE.md` | The project guide for Claude (agent instructions), with the AWS profile name redacted. |
| `skills/code-hygiene/SKILL.md` | The code-hygiene skill (provided at session start). |
| `skills/feature-workflow/SKILL.md` | The project feature-workflow skill created in the session. |
| `plans/history/01-06-*.md` | Each full plan the agent wrote before a feature (Features 1–4), recovered from the session log. These are pre-implementation snapshots, so the shipped code may differ: for example, tracing ended up controlled by the `--tracing/--no-tracing` CLI flag. Later small plan edits are visible only in the session log. |

There are no custom subagent definitions (`.claude/agents/`) in this project.
