# Feature 1 — LangSmith tracing driven by `.env` (project `tavily-research-agent`)

## Context
`.env` already holds the LangSmith key, `LANGSMITH_TRACING=true` and `LANGSMITH_PROJECT="UdemyCourse"`. LangChain traces automatically from these env vars, but runs currently go to the wrong project and nothing tells you whether tracing is on. The goal:
- tracing is on by default when `LANGSMITH_API_KEY` is set and off when it isn't;
- `.env` is the only source of settings, with no CLI flags and no helper functions;
- a `logging` line at startup reports the status and the project.

Branch: `feat/langsmith-tracing`. The only code changes are in `starter_agent.py`. No new dependencies.

## Changes

**1. `.env` (local, untracked)**: change the project value only:
```
LANGSMITH_PROJECT="tavily-research-agent"
```

**2. `starter_agent.py` imports**: add `logging`:
```python
import json
import logging
import os
```

**3. Module logger** (after `console = Console()`):
```python
logger = logging.getLogger(__name__)
```

**4. Start of `main()`** (before `require_env(...)`). The stream call is unchanged.
```python
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # LangChain traces automatically from LANGSMITH_* env vars; default tracing on when a key exists.
    if os.getenv("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGSMITH_TRACING", "true")
    else:
        os.environ["LANGSMITH_TRACING"] = "false"
    if os.environ["LANGSMITH_TRACING"].lower() == "true":
        logger.info("LangSmith tracing enabled (project: %s)", os.getenv("LANGSMITH_PROJECT", "default"))
    else:
        logger.info("LangSmith tracing disabled (set LANGSMITH_API_KEY in .env to enable)")
```
`setdefault` makes tracing on by default but still respects an explicit `LANGSMITH_TRACING=false` in `.env`. If the key is missing, tracing is forced off and the log says so.

## Tests — `tests/test_tracing.py` (new)
Each test invokes `main` through `typer.testing.CliRunner`. `create_agent` is replaced with a fake agent whose `stream()` yields nothing, so LangSmith, Bedrock and Tavily are never called. `TAVILY_API_KEY` is set and `LANGSMITH_*` are controlled with `monkeypatch`, which also restores `.env` values loaded at import.
1. Key set, `LANGSMITH_TRACING` unset, project `tavily-research-agent` → `LANGSMITH_TRACING == "true"`; the log contains `LangSmith tracing enabled (project: tavily-research-agent)`.
2. Key missing (even with `LANGSMITH_TRACING=true`) → `LANGSMITH_TRACING == "false"`; the log contains `LangSmith tracing disabled`.
3. Key set, `LANGSMITH_TRACING=false` → stays `"false"`; the log says disabled.

Test command, which needs the script's deps: `uv run --with pytest --with-requirements starter_agent.py pytest -q`. If uv can't read PEP 723 metadata this way, the fallback is `--with` per dependency. CLAUDE.md and the README "Checks" will be updated to whichever command works.

## Commits
1. `feat: enable LangSmith tracing from .env with startup log`: items 2–4 + tests.
2. `docs: document LangSmith tracing behaviour`: a README note (enabled when `LANGSMITH_API_KEY` is set; project from `LANGSMITH_PROJECT`) and the test command in CLAUDE.md/README. A summary goes to you before the README is written.
3. Push and open the PR with check output.

## Verification
- The test command → all pass. `uvx ruff check tests` → clean. No new ruff findings in the changed lines of `starter_agent.py`.
- Manual: `uv run starter_agent.py "What is Tavily?"` → `LangSmith tracing enabled (project: tavily-research-agent)`, and the run appears in LangSmith under `tavily-research-agent`.
- Manual: `LANGSMITH_API_KEY= uv run starter_agent.py "What is Tavily?"` → the disabled log line, and the agent still answers. `load_dotenv` doesn't override existing env vars, so the empty value takes effect.
