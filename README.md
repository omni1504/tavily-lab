# tavily-lab

A small research agent CLI built with LangChain and the Tavily search tool, running Claude on Amazon Bedrock. It streams the agent's answer, tool calls and results to the console.

## Setup

1. Install [uv](https://docs.astral.sh/uv/). Dependencies are declared inline in `starter_agent.py` (PEP 723), so `uv run` installs them.
2. Create a `.env` file with `TAVILY_API_KEY`. Optionally add `LANGSMITH_TRACING`, `LANGSMITH_ENDPOINT`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` to enable LangSmith tracing.
3. Make sure the AWS named profile configured in `starter_agent.py` has Bedrock access in the configured region.

## Run

```bash
uv run starter_agent.py "What are the latest trends in agent evaluation?"
```

## Checks

```bash
uvx ruff format --check .
uvx ruff check .
uvx pytest -q
```
