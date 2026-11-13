"""Tests for the stdio MCP server (no Bedrock/Tavily calls; generate_brief is faked)."""

import time
from typing import Any

import anyio
import pytest
import server

from starter_agent import BriefResult

pytestmark = pytest.mark.anyio

RESULT = BriefResult(
    answer="## Overview\n- Fact [A](https://a.com/1)\n",
    sources={"https://a.com/1": "A"},
    searches=[],
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeContext:
    def __init__(self) -> None:
        self.progress: list[tuple[float, str | None]] = []

    async def report_progress(
        self, progress: float, total: float | None = None, message: str | None = None
    ) -> None:
        self.progress.append((progress, message))


async def test_server_exposes_only_get_brief_with_expected_schema() -> None:
    tools = await server.mcp.list_tools()
    assert [t.name for t in tools] == ["get_brief"]
    schema = tools[0].inputSchema
    assert schema["required"] == ["company"]
    assert schema["properties"]["company"]["type"] == "string"
    assert schema["properties"]["include_sources"]["type"] == "boolean"
    assert "ctx" not in schema["properties"]
    assert "cited account brief" in (tools[0].description or "")


async def test_get_brief_returns_markdown_with_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        server.starter_agent,
        "generate_brief",
        lambda name: calls.append(name) or RESULT,
    )
    ctx: Any = FakeContext()
    assert await server.get_brief("  Acme  ", ctx) == RESULT.markdown()
    assert await server.get_brief("Acme", ctx, include_sources=False) == RESULT.answer
    assert calls == ["Acme", "Acme"]


@pytest.mark.parametrize("company", ["", "   ", "x" * 121])
async def test_get_brief_rejects_bad_company_names(company: str) -> None:
    ctx: Any = FakeContext()
    with pytest.raises(ValueError, match="1-120 characters"):
        await server.get_brief(company, ctx)


async def test_heartbeat_reports_progress_while_work_runs() -> None:
    ctx: Any = FakeContext()

    def slow() -> str:
        time.sleep(0.25)
        return "done"

    assert await server.run_with_heartbeat(slow, ctx, interval=0.05) == "done"
    assert len(ctx.progress) >= 3
    assert ctx.progress[0] == (0.0, "Researching (0s)")


async def test_heartbeat_propagates_the_original_error() -> None:
    def broken() -> str:
        raise RuntimeError("TAVILY_API_KEY is not set")

    ctx: Any = FakeContext()
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        await server.run_with_heartbeat(broken, ctx, interval=0.05)


async def test_heartbeat_stops_after_work_finishes() -> None:
    ctx: Any = FakeContext()
    await server.run_with_heartbeat(lambda: "x", ctx, interval=0.05)
    count = len(ctx.progress)
    await anyio.sleep(0.15)
    assert len(ctx.progress) == count


def test_script_pins_mcp_v1_api() -> None:
    """Regression: an unpinned `mcp` resolved to 2.x, where FastMCP no longer exists."""
    header = (
        (server.REPO_ROOT / "mcp_server" / "server.py").read_text().split("# ///")[1]
    )
    assert '"mcp>=1.13,<2"' in header
