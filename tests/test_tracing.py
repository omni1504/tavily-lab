"""LangSmith tracing is switched by --tracing/--no-tracing (default on); .env only holds the key."""

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

    def invoke(*flags: str) -> None:
        result = CliRunner().invoke(starter_agent.app, [*flags, "hello"])
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


def test_no_tracing_flag_disables_tracing(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    with caplog.at_level(logging.INFO):
        run_cli("--no-tracing")
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LangSmith tracing disabled (--no-tracing)" in caplog.text


def test_tracing_disabled_without_api_key(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with caplog.at_level(logging.INFO):
        run_cli("--tracing")
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "set LANGSMITH_API_KEY in .env to enable" in caplog.text


@pytest.mark.parametrize("env_value", ["true", "false"])
def test_langsmith_tracing_env_value_is_ignored(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch, env_value: str
) -> None:
    """The CLI flag is the switch now; a LANGSMITH_TRACING value from .env no longer decides."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    monkeypatch.setenv("LANGSMITH_TRACING", env_value)
    run_cli()
    assert os.environ["LANGSMITH_TRACING"] == "true"
    run_cli("--no-tracing")
    assert os.environ["LANGSMITH_TRACING"] == "false"
