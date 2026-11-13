---
name: feature-workflow
description: Mandatory branch → plan → small tested steps → PR workflow for every feature in the Tavily-Lab repo, plus config/secrets and Bedrock rules. Use whenever the user requests a new feature, change, or fix in this repo.
---

# Feature Workflow (Tavily-Lab)

Follow these steps for EVERY feature request. Also apply the `code-hygiene` skill.

## 1. Plan first (no code yet)
- Restate the feature in one line, then list: files to touch, small steps, tests per step, any new dependency (with why).
- Show the plan and WAIT for user approval before writing feature code.

## 2. Branch
- `git checkout main && git pull --ff-only origin main`
- `git checkout -b <type>/<short-kebab-name>` (e.g. `feat/multi-turn-chat`, `fix/stream-crash`).
- Never commit feature work directly to `main`.

## 3. Build in small steps
- Each step = code + its tests + passing checks from CLAUDE.md + one Conventional Commit.
- Extend `starter_agent.py` in place; no restructuring or new config layers unless asked.
- Tests must not call real Tavily, Bedrock, or LangSmith — mock/fake them.

## 4. Open the PR
- `git push -u origin <branch>`
- `gh pr create --base main --title "<conventional title>" --body "<summary, steps, test evidence>"`
- Include the final check output in the PR body. Report the PR URL to the user.
- Do not merge unless the user asks.

## Config & secrets
- All API keys (Tavily, LangSmith, others) come from `.env` via `python-dotenv`. Never hardcode, print, log, or commit them.
- `.env` and `.claude/` are git-ignored. Document any new variable name (never its value) in README.md.

## Amazon Bedrock
- Keep using the existing Bedrock config: profile `amirasf+genai`, region `us-west-2`, model `us.anthropic.claude-sonnet-4-6`.
- Do not change the profile, region, or model unless the user explicitly asks.
