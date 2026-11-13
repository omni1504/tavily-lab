# Project guide for Claude

Tavily + LangChain research-agent CLI running on Amazon Bedrock. Features are added iteratively.

## Stack
- Language: Python 3.12+
- Package manager: uv
- Key libs: LangChain (`create_agent`), `langchain-aws` (Bedrock Converse), `langchain-tavily`, Typer, Rich
- Layout: `src/` code, `tests/` tests, `docs/` docs.

## Commands
- `make fmt` · `make lint` · `make typecheck` · `make test` · `make check` (all of them)

## Configuration
- Secrets/API keys (Tavily, LangSmith, ...) live in `.env`, loaded with `python-dotenv`. Never hardcode, log, or commit them.
- AWS: Bedrock via named profile `amirasf+genai`, region `us-west-2`, model `us.anthropic.claude-sonnet-4-6`. Keep these as-is unless explicitly asked.
- LangSmith tracing is enabled through `LANGSMITH_*` env vars in `.env`.

## Workflow
- Always follow the `feature-workflow` skill: plan → user approval → branch per feature → small steps with tests → PR via `gh`.
- Remote: `https://github.com/omni1504/tavily-lab` (base branch `main`).

## Rules
- Always follow the `code-hygiene` skill.
- `make check` must pass before any task is considered done.
- Ask before: adding dependencies, changing public APIs, touching CI, deleting files, changing the Bedrock profile/model.
- Never commit `.env` or `.claude/`.
- Keep changes minimal and scoped to the request.
