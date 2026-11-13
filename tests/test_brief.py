"""--brief mode: account-research prompt, capped Tavily searches, unchanged default mode."""

import json
import os
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
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


def test_brief_prompt_requires_persona_sources_and_ticker_news_queries() -> None:
    prompt = starter_agent.brief_prompt(date(2026, 11, 13))
    assert "Name | Title | Relevance | Source" in prompt
    assert "every row's Source is its own [title](URL) link" in prompt
    assert "name plus its\n     stock ticker when it is publicly traded" in prompt
    assert "omit the ticker otherwise" in prompt


def test_brief_prompt_forbids_time_words_in_queries() -> None:
    """Regression: "latest ... 2026" matched an unrelated article's own subheadings."""
    prompt = starter_agent.brief_prompt(date(2026, 11, 13))
    assert 'Never add time words such as\n   "latest" or "recent", or a year' in prompt
    assert "start_date already sets the time window" in prompt


def test_brief_prompt_names_no_specific_company() -> None:
    """Examples naming a real company would bias every brief toward it."""
    assert "Snowflake" not in starter_agent.BRIEF_PROMPT


def test_llm_output_budget_fits_a_full_brief() -> None:
    """Regression: 4096 tokens (shared with adaptive thinking) truncated briefs."""
    assert starter_agent.llm.max_tokens == 64000


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


def test_record_writes_answer_searches_and_sources(cli: Any, tmp_path: Any) -> None:
    payload = tavily_payload("https://a.com/1")
    payload["results"][0].update(
        content="A text", published_date="2026-11-01", score=0.9
    )
    events: list[tuple[str, Any]] = [
        (
            "updates",
            {
                "model": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "c1",
                                    "name": "tavily_search",
                                    "args": {"query": "q"},
                                }
                            ],
                        )
                    ]
                }
            },
        ),
        (
            "updates",
            {
                "tools": {
                    "messages": [
                        ToolMessage(
                            content=json.dumps(payload),
                            tool_call_id="c1",
                            name="tavily_search",
                        )
                    ]
                }
            },
        ),
        ("messages", (AIMessageChunk(content="- Fact [A](https://a.com/1)\n"), {})),
    ]
    path = tmp_path / "out" / "acme.json"
    cli(["--brief", "--record", str(path), "Acme"], events)

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["input"] == "Acme"
    assert record["brief"] is True
    assert record["answer"] == "- Fact [A](https://a.com/1)\n"
    assert record["searches"] == [
        {
            "args": {"query": "q"},
            "results": [
                {
                    "url": "https://a.com/1",
                    "title": "T 1",
                    "content": "A text",
                    "published_date": "2026-11-01",
                    "score": 0.9,
                }
            ],
        }
    ]
    assert record["sources"] == {"https://a.com/1": "T 1"}
    assert record["duration_s"] >= 0


def test_no_record_file_without_flag(cli: Any, tmp_path: Any) -> None:
    cli(["--brief", "Acme"])
    assert list(tmp_path.iterdir()) == []


def test_brief_prompt_requires_citing_every_source_a_statement_uses() -> None:
    """Regression: Databricks eval found facts merged from several results but one citation."""
    prompt = starter_agent.brief_prompt(date(2026, 11, 13))
    assert (
        "combines facts from several search results, cite every one of them" in prompt
    )
    assert "Cite a source only for facts its text states" in prompt
    assert (
        "If sources disagree on a figure, give each value with its own source" in prompt
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "[W](https://en.wikipedia.org/wiki/Amazon_(company))",
            ["https://en.wikipedia.org/wiki/Amazon_(company)"],
        ),
        (
            "[A](https://a.com/x) and https://b.com/y.",
            ["https://a.com/x", "https://b.com/y."],
        ),
        ("<https://c.com/z>", ["https://c.com/z"]),
    ],
)
def test_url_pattern_keeps_balanced_parentheses(text: str, expected: list[str]) -> None:
    """Regression: Wikipedia URLs with "(...)" were cut and reported as unverified."""
    assert starter_agent.URL_PATTERN.findall(text) == expected


def test_appendix_verifies_urls_with_parentheses() -> None:
    url = "https://en.wikipedia.org/wiki/Amazon_(company)"
    appendix = starter_agent.build_source_appendix(
        f"- Fact [W]({url})", {url: "Amazon"}
    )
    assert f"- [Amazon]({url})" in appendix.split("Additional research")[0]
    assert appendix.rstrip().endswith("- None")


def finished_run_messages() -> list[Any]:
    payload = tavily_payload("https://a.com/1", "https://b.com/2")
    return [
        AIMessage(
            content="Searching now.",
            tool_calls=[
                {"id": "c1", "name": "tavily_search", "args": {"query": "Acme"}}
            ],
        ),
        ToolMessage(
            content=json.dumps(payload), tool_call_id="c1", name="tavily_search"
        ),
        AIMessage(content="## Overview\n- Fact [A](https://a.com/1)\n"),
    ]


def test_brief_result_collects_answer_sources_and_searches() -> None:
    result = starter_agent.brief_result(finished_run_messages())
    assert result.answer == "## Overview\n- Fact [A](https://a.com/1)\n"
    assert result.sources == {"https://a.com/1": "T 1", "https://b.com/2": "T 2"}
    assert result.searches[0]["args"] == {"query": "Acme"}
    assert [r["url"] for r in result.searches[0]["results"]] == [
        "https://a.com/1",
        "https://b.com/2",
    ]
    assert "- [T 1](https://a.com/1)" in result.appendix.split("Additional research")[0]
    assert result.markdown().startswith(result.answer)
    assert result.markdown().endswith(result.appendix)
    assert result.markdown(include_sources=False) == result.answer


class InvokingAgent:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        return {"messages": finished_run_messages()}


def test_generate_brief_runs_brief_agent_without_printing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = InvokingAgent()
    built: list[bool] = []
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setattr(
        starter_agent, "build_agent", lambda brief: built.append(brief) or agent
    )

    result = starter_agent.generate_brief("Acme", tracing=False)

    assert built == [True]
    assert agent.payload == {"messages": [{"role": "user", "content": "Account: Acme"}]}
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert result.answer.startswith("## Overview")
    assert capsys.readouterr().out == ""


def test_generate_brief_requires_tavily_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        starter_agent.generate_brief("Acme")
