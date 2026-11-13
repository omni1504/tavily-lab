# Feature 1 — Optional LangSmith tracing (project `tavily-research-agent`)

## Context
`starter_agent.py` already calls `load_dotenv()`, and `.env` currently contains `LANGSMITH_TRACING=true` and `LANGSMITH_PROJECT="UdemyCourse"`. That means runs are already traced implicitly, to the wrong project, with no visible status and no way to switch tracing per run. The goal is explicit, optional tracing:
- settings come from `.env`, with CLI flags that override them;
- the default project is `tavily-research-agent`;
- a `logging` line at startup says whether tracing is on and which project it uses.

## Approach
Use `langsmith.tracing_context(enabled=..., project_name=...)` around the agent stream instead of changing `os.environ`.
- langchain-core reads this context first: see `_tracing_v2_is_enabled` / `_get_tracer_kwargs` in `langchain_core/tracers/context.py` and `langsmith.utils.tracing_is_enabled`.
- `--no-tracing` therefore reliably overrides `LANGSMITH_TRACING=true`.
- It also avoids langsmith's `lru_cache`d env lookups going stale.

Precedence, highest first: CLI flag → `.env` → default (tracing off, project `tavily-research-agent`). Tracing is forced off, with a warning, if `LANGSMITH_API_KEY` is missing.

Branch: `feat/langsmith-tracing`. All code changes are in `starter_agent.py`, with no restructuring.

## Exact code changes — `starter_agent.py`

**1. PEP 723 deps** (needs approval: `langsmith` is already installed transitively at 0.14.17 via langchain-core; it's declared because we now import it directly):
```python
#   "langchain-tavily>=0.2.0",
#   "langsmith>=0.3.0",
#   "python-dotenv>=1.0.0",
```

**2. Imports** (the new lines are `logging`, `Iterator` and `tracing_context`):
```python
import json
import logging
import os
from collections.abc import Iterator
from typing import Annotated, Any
...
from langchain_tavily import TavilySearch
from langsmith import tracing_context
```

**3. Module constants and logger** (after `console = Console()`):
```python
logger = logging.getLogger(__name__)

DEFAULT_LANGSMITH_PROJECT = "tavily-research-agent"
```

**4. New helpers** (after `require_env`):
```python
def resolve_tracing(enabled: bool | None, project: str | None) -> tuple[bool, str]:
    """CLI values win over .env; tracing without an API key would fail on every run, so it is disabled."""
    if enabled is None:
        enabled = os.getenv("LANGSMITH_TRACING", "").strip().lower() == "true"
    project_name = project or os.getenv("LANGSMITH_PROJECT") or DEFAULT_LANGSMITH_PROJECT
    if enabled and not os.getenv("LANGSMITH_API_KEY"):
        logger.warning("LangSmith tracing requested but LANGSMITH_API_KEY is not set; tracing disabled")
        enabled = False
    return enabled, project_name


def log_tracing_status(enabled: bool, project_name: str) -> None:
    if enabled:
        logger.info("LangSmith tracing enabled (project: %s)", project_name)
    else:
        logger.info("LangSmith tracing disabled")


def traced_stream(
    agent: Any, payload: dict[str, Any], enabled: bool, project_name: str
) -> Iterator[tuple[str, Any]]:
    """Scope tracing to this run so a CLI flag can override LANGSMITH_TRACING in .env."""
    with tracing_context(enabled=enabled, project_name=project_name):
        yield from agent.stream(payload, stream_mode=["messages", "updates"])
```

**5. `main` signature: optional parameters**
```python
@app.command()
def main(
    question: Annotated[list[str], typer.Argument(help="Question")],
    tracing: Annotated[
        bool | None,
        typer.Option(
            "--tracing/--no-tracing",
            help="Enable LangSmith tracing. Default: LANGSMITH_TRACING from .env.",
        ),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            help=f"LangSmith project. Default: LANGSMITH_PROJECT from .env, else {DEFAULT_LANGSMITH_PROJECT}.",
        ),
    ] = None,
) -> None:
    """Ask a question and stream a small LangChain agent that searches with Tavily."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tracing_enabled, project_name = resolve_tracing(tracing, project)
    log_tracing_status(tracing_enabled, project_name)

    require_env(
    ...
```

**6. Stream call** (only this call changes; the loop is not re-indented):
```python
        stream = traced_stream(
            agent,
            {"messages": [{"role": "user", "content": question_text}]},
            tracing_enabled,
            project_name,
        )
```

## `.env` (local, untracked; needs your OK)
Change `LANGSMITH_PROJECT="UdemyCourse"` to `LANGSMITH_PROJECT="tavily-research-agent"`. Without this, the precedence rule sends traces to `UdemyCourse`.

## Tests — `tests/test_tracing.py` (new)
These import `starter_agent`. LangSmith, Bedrock and Tavily are not called: `create_agent` is replaced with a fake agent.
- `.env` value used when no flag: `LANGSMITH_TRACING=true` + key → `(True, env project)`.
- Flag overrides env: `--no-tracing` with `LANGSMITH_TRACING=true` → disabled.
- Project precedence: `--project` > `LANGSMITH_PROJECT` > `tavily-research-agent`.
- Missing `LANGSMITH_API_KEY` → disabled, with a WARNING record (`caplog`).
- `log_tracing_status` → the INFO message names the project; the disabled message is also checked.
- `traced_stream` → the fake agent's `stream()` yields `langsmith.run_helpers.get_tracing_context()`. The test asserts `enabled` / `project_name` are set while the stream runs and reset afterwards.
- CLI (`typer.testing.CliRunner`): with `create_agent` monkeypatched to a fake agent and `TAVILY_API_KEY` set, the startup log contains `LangSmith tracing enabled (project: tavily-research-agent)`. A second case covers `--no-tracing`.

Test command, which needs the script's deps: `uv run --with pytest --with-requirements starter_agent.py pytest -q`. If uv can't read PEP 723 through `--with-requirements`, the fallback is listing the deps with `--with`. CLAUDE.md and the README "Checks" will be updated to the working command.

## Steps / commits
1. `feat: add optional LangSmith tracing with startup log` — items 1–6 + tests.
2. `docs: document tracing flags and LANGSMITH_* in README` — README Run section gets `--tracing/--no-tracing` and `--project`; CLAUDE.md gets the test command. A summary goes to you before the README is written.
3. Push and open the PR with check output.

## Verification
- `uv run --with pytest --with-requirements starter_agent.py pytest -q` → all pass.
- `uvx ruff check tests` and ruff on the changed code → no new findings.
- Manual: `uv run starter_agent.py "What is Tavily?"` → log line `LangSmith tracing enabled (project: tavily-research-agent)`, and the run appears in LangSmith project `tavily-research-agent`.
- `uv run starter_agent.py --no-tracing "What is Tavily?"` → `LangSmith tracing disabled`, and no new trace.
