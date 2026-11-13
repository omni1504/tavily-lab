"""--brief mode: account-research prompt, capped Tavily searches, unchanged default mode."""

import json
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import AIMessageChunk, ToolMessage
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


def tavily_payload(*urls: str) -> dict[str, Any]:
    return {
        "query": "q",
        "results": [{"url": url, "title": f"T {url[-1]}"} for url in urls],
    }


def test_collect_sources_parses_json_string_and_dict_without_duplicates() -> None:
    sources: dict[str, str] = {}
    starter_agent.collect_sources(json.dumps(tavily_payload("https://a.com")), sources)
    starter_agent.collect_sources(
        tavily_payload("https://a.com", "https://b.com"), sources
    )
    assert sources == {"https://a.com": "T m", "https://b.com": "T m"}


@pytest.mark.parametrize(
    "content",
    [
        "Tool call limit exceeded. Do not call 'tavily_search' again.",
        ["not", "a", "dict"],
        {"results": [{"title": "no url"}, "not a dict"]},
        {"no_results_key": True},
    ],
)
def test_collect_sources_ignores_non_search_content(content: Any) -> None:
    sources: dict[str, str] = {}
    starter_agent.collect_sources(content, sources)
    assert sources == {}


def test_collect_sources_defaults_missing_title() -> None:
    sources: dict[str, str] = {}
    starter_agent.collect_sources({"results": [{"url": "https://x.io"}]}, sources)
    assert sources == {"https://x.io": "Untitled"}


def test_appendix_splits_verified_additional_and_unverified() -> None:
    sources = {
        "https://a.com/news/": "A news",
        "https://b.com/page": "B page",
    }
    answer = (
        "- Fact one [A](https://a.com/news).\n"
        "- Fact two https://a.com/news/.\n"
        "- Made up [X](https://invented.example/x)\n"
        "- Talking point (No citation)\n"
    )
    appendix = starter_agent.build_source_appendix(answer, sources)
    verified, additional, unverified = appendix.split("\n\n")

    assert verified.splitlines() == [
        "## Sources (cited, returned by Tavily)",
        "- [A news](https://a.com/news/)",
    ]
    assert additional.splitlines() == [
        "## Additional research (returned by Tavily, not cited)",
        "- [B page](https://b.com/page)",
    ]
    assert unverified.splitlines() == [
        "## Unverified citations (not returned by Tavily)",
        "- https://invented.example/x",
    ]


def test_appendix_shows_none_for_empty_groups() -> None:
    appendix = starter_agent.build_source_appendix("No links here.", {})
    assert appendix.count("- None") == 3


def test_brief_mode_prints_appendix_from_tool_output(cli: Any) -> None:
    events: list[tuple[str, Any]] = [
        (
            "updates",
            {
                "tools": {
                    "messages": [
                        ToolMessage(
                            content=json.dumps(
                                tavily_payload("https://a.com/1", "https://b.com/2")
                            ),
                            tool_call_id="call-1",
                            name="tavily_search",
                        )
                    ]
                }
            },
        ),
        (
            "messages",
            (AIMessageChunk(content="## Overview\n- Fact [A](https://a.com/1)\n"), {}),
        ),
        ("messages", (AIMessageChunk(content="- Guess [Z](https://z.org/9)\n"), {})),
    ]
    _kwargs, _agent, output = cli(["--brief", "Snowflake"], events)

    sources_part = output.split("Sources (from Tavily tool output)")[1]
    assert "- [T 1](https://a.com/1)" in sources_part
    assert "- [T 2](https://b.com/2)" in sources_part
    assert "- https://z.org/9" in sources_part
    assert sources_part.index("https://a.com/1") < sources_part.index(
        "Additional research"
    )
    assert sources_part.index("https://b.com/2") > sources_part.index(
        "Additional research"
    )
    assert sources_part.index("https://z.org/9") > sources_part.index(
        "Unverified citations"
    )


def test_stream_ignores_empty_middleware_updates(cli: Any) -> None:
    """Regression: ToolCallLimitMiddleware emits a None update when it changes nothing."""
    events: list[tuple[str, Any]] = [
        (
            "messages",
            (AIMessageChunk(content="## Overview\n- Fact (No citation)\n"), {}),
        ),
        ("updates", {"ToolCallLimitMiddleware[tavily_search].after_model": None}),
    ]
    _kwargs, _agent, output = cli(["--brief", "Snowflake"], events)
    assert "Agent run failed" not in output
    assert "Sources (from Tavily tool output)" in output
