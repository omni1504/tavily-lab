# tavily-lab

A small research agent CLI built with LangChain and the Tavily search tool, running Claude on Amazon Bedrock. It streams the agent's answer, tool calls and results to the console.

## Setup

1. Install [uv](https://docs.astral.sh/uv/). Dependencies are declared inline in `starter_agent.py` (PEP 723), so `uv run` installs them.
2. Create a `.env` file with `TAVILY_API_KEY`. For LangSmith tracing, also add `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT` and `LANGSMITH_PROJECT` (this repo uses `tavily-research-agent`).
   - Tracing is on whenever `LANGSMITH_API_KEY` is set. Set `LANGSMITH_TRACING=false` to turn it off.
   - The script logs at startup whether tracing is enabled and which project it uses.
3. Make sure the AWS named profile configured in `starter_agent.py` has Bedrock access in the configured region.

## Run

```bash
uv run starter_agent.py "What are the latest trends in agent evaluation?"
```

### Account brief (`--brief`)

Use this mode to prepare a Sales Representative or Technical Presales engineer for a meeting. Pass an account name instead of a question:

```bash
uv run starter_agent.py --brief "Acme Corp"
```

The brief has these sections: **Overview**, **Recent news** (last 90 days), **Strategic priorities**, **Main personas** (a table with a source for each row), and **Suggested talking points** (Sales and Technical).

- **Searches:** the agent first runs four Tavily searches together: overview, news (filtered by start date, using the ticker for public companies), strategy and leadership. It runs a refined follow-up search only when a section has too few results. A hard limit of 10 Tavily calls per brief is enforced in code with LangChain's `ToolCallLimitMiddleware`.
- **Citations:** every statement ends with a source link, or `(No citation)` when it is the model's own inference, such as most talking points.
- **Sources appendix:** after the brief, the script prints three lists built from the actual Tavily tool output, not from the model:
  - **Sources:** cited URLs that Tavily returned.
  - **Additional research:** URLs Tavily returned that the brief doesn't cite.
  - **Unverified citations:** URLs in the brief that Tavily never returned.
- **Limits:** the appendix shows whether a URL came from search, not whether it supports the statement it's attached to. A typical brief uses 4–7 Tavily credits.

## Checks

```bash
uvx ruff format --check .
uvx ruff check .
uv run --with pytest --with-requirements starter_agent.py pytest -q
```

Tests import `starter_agent.py`, so they run with the script's inline dependencies.
