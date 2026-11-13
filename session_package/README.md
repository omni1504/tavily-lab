# Session package (not committed)

This folder holds the artifacts from the Claude Code session `9ded8427-f5c3-41bd-a29a-9e2affa1885a`, in which the Tavily-Lab features were built (2026-11-13). It's excluded from git through `.git/info/exclude`.

| Path | Contents |
|---|---|
| `plans/precious-scribbling-acorn.md` | The session's plan file in its **final** state (Feature 4: MCP server). The same file was reused for every feature. |
| `plans/history/01-06-*.md` | Each full version of that plan file as it was written during the session (Features 1–4), recovered from the session log. Later small edits are visible only in the session log. |
| `plans/look-at-the-sample-happy-pillow.md` | An earlier plan for this project from a previous session ("Grounded, cited, traced" Tavily agent). |
| `samples/session.jsonl` | A snapshot of the raw session log. |
| `samples/session.md` | The same log rendered with `parser/parse_session.py`. |
| `skills/code-hygiene/SKILL.md` | The code-hygiene skill (provided at session start). |
| `skills/feature-workflow/SKILL.md` | The project feature-workflow skill created in the session. |
| `agent/CLAUDE.md` | The project guide for Claude (agent instructions). |
| `agent/memory/` | Project memory notes Claude saved during the session. `MEMORY.md` is the index. |

There are no custom subagent definitions (`.claude/agents/`) in this project.
