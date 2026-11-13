"""--brief mode: account-research prompt, capped Tavily searches, unchanged default mode."""

from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import ToolCallLimitMiddleware
from typer.testing import CliRunner

import starter_agent


class RecordingAgent:
    """Stands in for the LangChain agent; records the payload and replays canned events."""

    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self.events = events
        self.payload: dict[str, Any] | None = None

    def stream(self, payload: dict[str, Any], **_kwargs: Any) -> Iterator[Any]:
        self.payload = payload
        return iter(self.events)


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Run the CLI with fake Tavily/agent; returns (create_agent kwargs, agent, output)."""
    monkeypatch.setattr(
        starter_agent, "TavilySearch", lambda: SimpleNamespace(name="tavily_search")
    )
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    def invoke(
        args: list[str], events: list[tuple[str, Any]] | None = None
    ) -> tuple[dict[str, Any], RecordingAgent, str]:
        agent = RecordingAgent(events or [])
        captured: dict[str, Any] = {}

        def fake_create_agent(**kwargs: Any) -> RecordingAgent:
            captured.update(kwargs)
            return agent

        monkeypatch.setattr(starter_agent, "create_agent", fake_create_agent)
        result = CliRunner().invoke(starter_agent.app, args)
        assert result.exit_code == 0, result.output
        return captured, agent, result.output

    yield invoke


def test_brief_prompt_injects_dates_cap_sections_and_citation_rules() -> None:
    prompt = starter_agent.brief_prompt(date(2026, 11, 13))
    assert "Today is 2026-11-13" in prompt
    assert 'topic="news", start_date="2026-08-15"' in prompt
    assert "Never exceed 10 searches" in prompt
    for heading in (
        "## Overview",
        "## Recent news (since 2026-08-15)",
        "## Strategic priorities",
        "## Main personas",
        "## Suggested talking points",
    ):
        assert heading in prompt
    assert "(No citation)" in prompt


def test_brief_mode_uses_brief_prompt_account_message_and_search_cap(
    cli: Any,
) -> None:
    kwargs, agent, output = cli(["--brief", "Snowflake"])

    assert kwargs["system_prompt"] == starter_agent.brief_prompt(date.today())
    [limit] = kwargs["middleware"]
    assert isinstance(limit, ToolCallLimitMiddleware)
    assert limit.tool_name == "tavily_search"
    assert limit.run_limit == 10
    assert agent.payload == {
        "messages": [{"role": "user", "content": "Account: Snowflake"}]
    }
    assert "Account brief" in output


def test_default_mode_is_unchanged(cli: Any) -> None:
    kwargs, agent, output = cli(["What", "is", "Tavily?"])

    assert kwargs["system_prompt"] == starter_agent.SYSTEM_PROMPT
    assert kwargs["middleware"] == []
    assert agent.payload == {
        "messages": [{"role": "user", "content": "What is Tavily?"}]
    }
    assert "Question" in output
    assert "Account brief" not in output
