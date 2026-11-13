"""LangSmith tracing is driven by .env: on when LANGSMITH_API_KEY is set, off otherwise."""

import logging
import os
from collections.abc import Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

import starter_agent


class FakeAgent:
    def stream(self, *_args: Any, **_kwargs: Any) -> Iterator[Any]:
        return iter(())


@pytest.fixture
def run_cli(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(starter_agent, "create_agent", lambda **_kwargs: FakeAgent())
    monkeypatch.setattr(starter_agent, "TavilySearch", lambda: object())
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("LANGSMITH_PROJECT", "tavily-research-agent")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    def invoke() -> None:
        result = CliRunner().invoke(starter_agent.app, ["hello"])
        assert result.exit_code == 0, result.output

    yield invoke


def test_tracing_enabled_by_default_when_api_key_set(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    with caplog.at_level(logging.INFO):
        run_cli()
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert "LangSmith tracing enabled (project: tavily-research-agent)" in caplog.text


def test_tracing_disabled_without_api_key(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with caplog.at_level(logging.INFO):
        run_cli()
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LangSmith tracing disabled" in caplog.text


def test_explicit_tracing_false_in_env_is_respected(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    with caplog.at_level(logging.INFO):
        run_cli()
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LangSmith tracing disabled" in caplog.text
