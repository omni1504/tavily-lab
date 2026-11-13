# Project guide for Claude

Tavily + LangChain research-agent CLI running on Amazon Bedrock. Features are added iteratively.

## Stack
- Language: Python 3.11+ (`.python-version` pins 3.13 for uv)
- Package manager: uv (dependencies declared inline in `starter_agent.py` and `evals/run_evals.py`, PEP 723)
- Key libs: LangChain (`create_agent`), `langchain-aws` (Bedrock Converse), `langchain-tavily`, Typer, Rich
- Layout:
  - `starter_agent.py`: the app, as a single file;
  - `tests/`: app tests;
  - `evals/`: the eval framework and its tests (criteria in `evals/SCORING.md`);
  - `parser/`: the session log prettifier.

## Commands
- Run: `uv run starter_agent.py "<question>"`. Brief: `--brief "<account>"`. Options: `--no-tracing`, `--record out.json`.
- Format: `uvx ruff format .` · Lint: `uvx ruff check .` · Tests (app and evals): `uv run --with pytest --with-requirements starter_agent.py pytest -q`
- Evals:
  - `uv run evals/run_evals.py collect --companies <name>` (spends Tavily credits; needs an explicit selection);
  - `uv run evals/run_evals.py score <results-dir>` (judge only).
  - Prefer re-scoring saved records over re-collecting.

## Configuration
- Secrets/API keys (Tavily, LangSmith, ...) live in `.env`, loaded with `python-dotenv`. Never hardcode, log, or commit them.
- AWS: Bedrock via named profile `amirasf+genai`, region `us-west-2`, model `us.anthropic.claude-sonnet-4-6`, as set in `starter_agent.py`. Keep these unless explicitly asked.
- LangSmith tracing is switched by the CLI (`--tracing`, the default, or `--no-tracing`) and needs `LANGSMITH_API_KEY` in `.env`. `LANGSMITH_TRACING` in `.env` is ignored. The project comes from `LANGSMITH_PROJECT` (`tavily-research-agent`). Startup logs the tracing status. Evals always run with tracing off.

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
