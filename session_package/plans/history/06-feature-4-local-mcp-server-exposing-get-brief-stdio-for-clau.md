# Feature 4 — Local MCP server exposing `get_brief` (stdio, for Claude and Quick Desktop)

## Context
Today the account brief is only available from the terminal (`starter_agent.py --brief`). Users want to ask for a company report from their local AI apps (Claude Code, Claude Desktop, Quick Desktop). These apps launch local MCP servers as a child process and talk to them over **stdio**.

This feature adds a lightweight **stdio-only** MCP server in its own folder. It exposes one tool, `get_brief(company)`, and calls the agent through a new function that runs without console output.
- **No network exposure:** no HTTP transport and no listening socket, now or in future (your decision).
- **Agent and CLI behaviour stay as they are.**

Branch: `feat/mcp-server` (from `main`; PR #12 is merged).

## 1. `starter_agent.py`: add a programmatic entry point (small, behaviour-preserving)
The CLI keeps its streaming console path. Shared setup moves into helpers, so the CLI and MCP paths build the same agent:

```python
BRIEF_USER_MESSAGE = "Account: {account}"


def configure_tracing(tracing: bool) -> bool:
    """Moved out of main() unchanged: --tracing/--no-tracing decides LANGSMITH_TRACING."""
    ...  # the existing block from main(), returns tracing_enabled


def build_agent(brief: bool) -> Any:
    """Moved out of main(): same prompt, Tavily tool and search cap for every entry point."""
    search_tool = TavilySearch()
    middleware = (
        [ToolCallLimitMiddleware(tool_name=search_tool.name, run_limit=BRIEF_MAX_SEARCHES)]
        if brief
        else []
    )
    return create_agent(
        model=llm,
        tools=[search_tool],
        system_prompt=brief_prompt(date.today()) if brief else SYSTEM_PROMPT,
        middleware=middleware,
    )


@dataclass(frozen=True)
class BriefResult:
    answer: str
    sources: dict[str, str]
    searches: list[dict[str, Any]]

    @property
    def appendix(self) -> str:
        return build_source_appendix(self.answer, self.sources)

    def markdown(self, include_sources: bool = True) -> str:
        if not include_sources:
            return self.answer
        return f"{self.answer}\n\n---\n\n{self.appendix}"


def brief_result(messages: list[Any]) -> BriefResult:
    """Collect sources and searches from the run's messages; the answer is the final AI text."""
    ...  # reuses collect_sources(), search_results(), message_text()


def generate_brief(account: str, *, tracing: bool = True) -> BriefResult:
    """Run --brief without printing anything. stdout belongs to the MCP protocol."""
    if not os.getenv("TAVILY_API_KEY"):
        raise RuntimeError("TAVILY_API_KEY is not set (add it to .env)")
    configure_tracing(tracing)
    agent = build_agent(brief=True)
    state = agent.invoke(
        {"messages": [{"role": "user", "content": BRIEF_USER_MESSAGE.format(account=account)}]}
    )
    return brief_result(state["messages"])
```
- `main()` calls `configure_tracing()` and `build_agent()` in place of its current inline code. The stream loop, printing, `--record` and the appendix are unchanged.
- `generate_brief` never prints. Logging goes to stderr, which is already the default for `logging.basicConfig`.
- **Tracing:** on by default, like the CLI, so MCP calls appear in LangSmith `tavily-research-agent`.

## 2. `mcp_server/server.py` (new folder)
The folder is named `mcp_server/`, not `mcp/`, because a local `mcp/` folder would shadow the `mcp` SDK package. The script lists its dependencies inline (PEP 723): the agent's dependencies plus **`mcp`, the official Model Context Protocol Python SDK** (`FastMCP`). **That's the one new dependency, so it needs your approval.**

```python
mcp = FastMCP("tavily-account-brief")
MAX_COMPANY_CHARS = 120
HEARTBEAT_S = 10


@mcp.tool()
async def get_brief(company: str, ctx: Context, include_sources: bool = True) -> str:
    """Research a company with Tavily web search and return a cited account brief (Markdown)
    for a Sales Representative and a Technical Presales engineer: Overview, Recent news
    (90 days), Strategic priorities, Main personas, Suggested talking points, and a sources
    appendix built from the actual search results. Takes about 1 minute and uses 4-10 Tavily
    searches per call."""
    name = company.strip()
    if not name or len(name) > MAX_COMPANY_CHARS:
        raise ValueError(f"company must be 1-{MAX_COMPANY_CHARS} characters")
    result = await run_with_heartbeat(lambda: starter_agent.generate_brief(name), ctx)
    return result.markdown(include_sources)
```
- **`run_with_heartbeat`:** runs the blocking agent in a worker thread (`anyio.to_thread`) and calls `ctx.report_progress(...)` every 10 s. A brief takes about 45–75 s, and some clients time out tools that send no progress. It's about 15 lines.
- **Startup:** `main()` sets up logging to **stderr** and calls `mcp.run()` (stdio is the default). `sys.path` points at the repo root so `starter_agent` can be imported. `load_dotenv()` in `starter_agent` finds `.env` relative to that file, so the client's working directory doesn't matter. This will be verified.
- **Errors:** missing key, Bedrock or Tavily failures, and invalid input become MCP tool errors, which `FastMCP` produces from raised exceptions. They're never swallowed.

## 3. Client registration (docs only, no repo config that auto-registers)
- **Claude Code:** `claude mcp add tavily-brief -- uv run --script <repo>/mcp_server/server.py`
- **Claude Desktop / Quick Desktop** (their MCP JSON config):
  ```json
  {"mcpServers": {"tavily-brief": {"command": "<absolute path to uv>",
    "args": ["run", "--script", "<repo>/mcp_server/server.py"]}}}
  ```
  Desktop apps often don't inherit your shell `PATH`, so use the absolute path from `which uv`.

## 4. Tests
- **`tests/test_brief.py`** (agent):
  - `brief_result` built from fake `AIMessage` (tool calls), `ToolMessage` and a final `AIMessage` → returns the answer, sources and searches. The appendix lists verified URLs.
  - `generate_brief` with `build_agent` monkeypatched to a fake whose `invoke` returns canned messages. It checks the `Account: X` message, that tracing is applied, and that a missing `TAVILY_API_KEY` raises. It also checks that nothing is written to stdout (`capsys`).
  - The existing CLI tests keep passing unchanged, which shows `main()` behaves the same.
- **`mcp_server/test_server.py`**, using the anyio pytest plugin that ships with `mcp`:
  - `mcp.list_tools()` exposes exactly `get_brief`, with a `company` string and an optional `include_sources` boolean.
  - `get_brief` returns `generate_brief(...).markdown()` (monkeypatched), and `include_sources=False` returns the answer only.
  - Empty or over-long `company` raises.
  - The heartbeat calls `ctx.report_progress` while the work runs (fake ctx, short interval).
- **Test command** gains the MCP dependency:
  `uv run --with pytest --with-requirements starter_agent.py --with-requirements mcp_server/server.py pytest -q`
  If uv rejects the repeated flag, I'll fall back to `--with mcp`. README and CLAUDE.md are updated.

## Steps / commits
1. `refactor: extract configure_tracing and build_agent from main()`. Existing tests must pass unchanged.
2. `feat: add generate_brief() for programmatic runs` + tests.
3. `feat: add stdio MCP server exposing get_brief` (`mcp_server/server.py`, `conftest.py`, tests).
4. `docs:` README "Use from Claude / Quick Desktop" section and CLAUDE.md (layout, commands, test command). A summary goes to you first.
5. Push and open the PR.

## Verification
- **Unit tests and ruff:** clean on all changed and new files.
- **Protocol check, no credits:** a local stdio client from the `mcp` SDK starts the server and lists its tools. `get_brief` must be present with the right schema, and stdout must contain only protocol messages.
- **One live call** (about 4–10 Tavily credits): `get_brief("Tavily")` through that client. It should return the brief plus the sources appendix, and a trace should appear in LangSmith.
- **You** register the server in Claude Code or Desktop, or Quick Desktop, and ask for a brief there.
