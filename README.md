# tavily-lab

A small research agent CLI built with LangChain and the Tavily search tool, running Claude on Amazon Bedrock. It streams the agent's answer, tool calls and results to the console.

## Setup

1. Install [uv](https://docs.astral.sh/uv/). Dependencies are declared inline in `starter_agent.py` (PEP 723), so `uv run` installs them.
2. Create a `.env` file with `TAVILY_API_KEY`. For LangSmith tracing, also add `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT` and `LANGSMITH_PROJECT` (this repo uses `tavily-research-agent`).
   - Tracing is controlled by the CLI: it's on by default (`--tracing`) and needs `LANGSMITH_API_KEY`. Pass `--no-tracing` to turn it off. `LANGSMITH_TRACING` in `.env` no longer has any effect.
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
- **Limits:** the appendix shows whether a URL came from search, not whether it supports the statement it's attached to. A typical brief uses 4–8 Tavily credits.
- **Record:** `--record run.json` saves the brief, every Tavily call with its results, and the source URLs to a JSON file. The evals use this.

## Evals (`evals/`)

A separate program scores `--brief` output against a configurable golden set (`evals/golden_set.toml`: Nebius, Amazon, Snowflake, Cisco, Databricks). It uses deterministic checks plus an LLM judge on the same Bedrock model. Everything stays local, with no LangSmith tracing. **The scoring criteria are documented in [evals/SCORING.md](evals/SCORING.md).**

```bash
uv run evals/run_evals.py collect --companies Databricks   # runs the agent: spends Tavily credits
uv run evals/run_evals.py collect --all                     # whole golden set (~20–40 credits)
uv run evals/run_evals.py score evals/results/<run>         # judge only: no agent or Tavily calls
uv run evals/run_evals.py score evals/results/<run> --skip-judge   # deterministic checks only
```

- `collect` refuses to run without `--companies` or `--all`, so credits are never spent by accident. Companies run one at a time.
- `score` re-scores saved records, so you can change the criteria without re-running the agent.
- Results go to `evals/results/<timestamp>/` (git-ignored):
  - `report.md`: the scorecard, plus what failed and why;
  - `scores.csv`;
  - per company: `*.scores.json`, `*.record.json` and `*.console.log`.
- The golden set's `reference_facts` are prefilled; verify them before relying on check Q1.

## Use from Claude / Quick Desktop (MCP)

`mcp_server/server.py` is a local MCP server with one tool: `get_brief(company, include_sources=True)`. It returns the account brief as Markdown, plus the sources appendix.
- **Cost and time:** a call takes 1–3 minutes and uses 4–10 Tavily searches.
- **Transport:** stdio only, so no network port is opened.
- **Tracing:** on, so calls appear in LangSmith.

Register it in your client:

```bash
claude mcp add tavily-brief -- uv run --script <repo>/mcp_server/server.py   # Claude Code
```

```json
{"mcpServers": {"tavily-brief": {"command": "<output of `which uv`>",
  "args": ["run", "--script", "<repo>/mcp_server/server.py"]}}}
```

The JSON form is for Claude Desktop and Quick Desktop. Use absolute paths, because desktop apps don't inherit your shell `PATH`.

## Checks

```bash
uvx ruff format --check .
uvx ruff check .
uv run --with pytest --with-requirements starter_agent.py --with-requirements mcp_server/server.py pytest -q
```

Tests import the scripts, so they run with the scripts' inline dependencies.
