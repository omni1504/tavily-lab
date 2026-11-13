# Project guide for Claude

Tavily + LangChain research-agent CLI running on Amazon Bedrock. Features are added iteratively.

## Stack
- Language: Python 3.11+
- Package manager: uv (dependencies declared inline in `starter_agent.py`, PEP 723)
- Key libs: LangChain (`create_agent`), `langchain-aws` (Bedrock Converse), `langchain-tavily`, Typer, Rich
- Layout: `starter_agent.py` (the app, single file), `tests/` tests.

## Commands
- Run: `uv run starter_agent.py "<question>"`
- Format: `uvx ruff format .` · Lint: `uvx ruff check .` · Tests: `uvx pytest -q`

## Configuration
- Secrets/API keys (Tavily, LangSmith, ...) live in `.env`, loaded with `python-dotenv`. Never hardcode, log, or commit them.
- AWS: Bedrock via named profile `amirasf+genai`, region `us-west-2`, model `us.anthropic.claude-sonnet-4-6`, as set in `starter_agent.py`. Keep these unless explicitly asked.
- LangSmith tracing is enabled through `LANGSMITH_*` env vars in `.env`.

## Workflow
- Always follow the `feature-workflow` skill: plan → user approval → branch per feature → small steps with tests → PR via `gh`.
- Remote: `https://github.com/omni1504/tavily-lab` (private, base branch `main`).

## Rules
- Always follow the `code-hygiene` skill, using the commands above as its equivalents.
- Tests must pass and changed code must add no new ruff findings before any task is considered done.
- Keep the existing implementation in `starter_agent.py`; don't restructure it or add config frameworks unless asked.
- Ask before: adding dependencies, changing public APIs, touching CI, deleting files, changing the Bedrock profile/model.
- Never commit `.env` or `.claude/`.
- Keep changes minimal and scoped to the request.
