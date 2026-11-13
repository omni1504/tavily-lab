# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "langchain>=1.0.0",
#   "langchain-aws>=1.7.6",
#   "langchain-tavily>=0.2.0",
#   "mcp>=1.13,<2",  # code uses the v1 FastMCP API (renamed MCPServer in v2)
#   "python-dotenv>=1.0.0",
#   "rich>=13.0.0",
#   "typer>=0.12.0",
# ]
# ///
"""Local stdio MCP server exposing the account-brief agent as one tool, `get_brief`.

Started by an MCP client (Claude Code, Claude Desktop, Quick Desktop) as a child process:
    uv run --script mcp_server/server.py

stdio only: no network port is opened. stdout carries the MCP protocol, so nothing else may
print to it; logs go to stderr.
"""

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import anyio
from mcp.server.fastmcp import Context, FastMCP

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import starter_agent

MAX_COMPANY_CHARS = 120
HEARTBEAT_S = 10.0

T = TypeVar("T")
logger = logging.getLogger("tavily-brief-mcp")
mcp = FastMCP("tavily-account-brief")


async def _heartbeat(ctx: Context, interval: float) -> None:
    elapsed = 0.0
    while True:
        await ctx.report_progress(elapsed, message=f"Researching ({int(elapsed)}s)")
        await anyio.sleep(interval)
        elapsed += interval


async def run_with_heartbeat(
    work: Callable[[], T], ctx: Context, interval: float = HEARTBEAT_S
) -> T:
    """Run blocking work in a thread; progress notifications keep clients from timing out
    a call that takes about a minute.

    A plain task (not a task group) so the work's own exception reaches the client unwrapped
    instead of as an ExceptionGroup.
    """
    beat = asyncio.create_task(_heartbeat(ctx, interval))
    try:
        return await anyio.to_thread.run_sync(work)
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


def validated_company(company: str) -> str:
    name = company.strip()
    if not name or len(name) > MAX_COMPANY_CHARS:
        raise ValueError(f"company must be 1-{MAX_COMPANY_CHARS} characters")
    return name


@mcp.tool()
async def get_brief(company: str, ctx: Context, include_sources: bool = True) -> str:
    """Research a company with Tavily web search and return a cited account brief (Markdown)
    for a Sales Representative and a Technical Presales engineer: Overview, Recent news
    (last 90 days), Strategic priorities, Main personas and Suggested talking points, plus a
    sources appendix built from the actual search results. Takes about one minute and uses
    4-10 Tavily searches per call.

    Args:
        company: Company name, e.g. "Databricks".
        include_sources: Append the sources appendix (cited, additional, unverified URLs).
    """
    name = validated_company(company)
    logger.info("get_brief(%r)", name)
    result = await run_with_heartbeat(lambda: starter_agent.generate_brief(name), ctx)
    return result.markdown(include_sources)


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
