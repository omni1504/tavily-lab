"""Tests for the eval runner: credit guard, agent invocation, scoring and report (no network)."""

import json
from pathlib import Path
from typing import Any

import pytest
import run_evals
import typer
from langchain_core.exceptions import OutputParserException
from scoring import Company
from typer.testing import CliRunner

ACME = Company("Acme", "ACMX", ("acme.com",), ())
OTHER = Company("Other", None, ("other.io",), ())

GOOD_ANSWER = """## Overview
- Acme makes widgets [About](https://acme.com/about)
## Recent news
- **2026-11-01** Acme launched X [PR](https://acme.com/pr)
## Strategic priorities
- Grow [About](https://acme.com/about)
## Main personas
| Name | Title | Relevance | Source |
|---|---|---|---|
| Jane | CEO | Buyer | [About](https://acme.com/about) |
## Suggested talking points
### Sales
- Value (No citation)
### Technical
- APIs (No citation)
"""


def record() -> dict[str, Any]:
    return {
        "input": "Acme",
        "brief": True,
        "date": "2026-11-13",
        "answer": GOOD_ANSWER,
        "searches": [{"args": {"query": "Acme ACMX", "topic": "news"}, "results": []}],
        "sources": {"https://acme.com/about": "About", "https://acme.com/pr": "PR"},
    }


def judge_result(j1: float = 1.0, q_mean: float = 4.5) -> dict[str, Any]:
    return {
        "claims": [],
        "J": {"J1_supported": j1, "J2_main_subject_news": 1.0, "J3_event_date": 1.0},
        "Q": {"usefulness": {"score": 5, "rationale": "good"}},
        "Q_mean": q_mean,
    }


@pytest.mark.parametrize(
    ("names", "run_all"), [(None, False), (["Acme"], True)], ids=["none", "both"]
)
def test_selection_requires_exactly_one_of_companies_or_all(
    names: list[str] | None, run_all: bool
) -> None:
    with pytest.raises(typer.BadParameter, match="--companies NAME ... or --all"):
        run_evals.select_companies([ACME, OTHER], names, run_all)


def test_selection_by_name_is_case_insensitive_and_rejects_unknown() -> None:
    assert run_evals.select_companies([ACME, OTHER], ["acme"], False) == [ACME]
    assert run_evals.select_companies([ACME, OTHER], None, True) == [ACME, OTHER]
    with pytest.raises(typer.BadParameter, match="not in golden set: Nope"):
        run_evals.select_companies([ACME], ["Nope"], False)


def test_collect_without_selection_never_runs_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("agent must not run")

    monkeypatch.setattr(run_evals, "run_agent", fail)
    result = CliRunner().invoke(run_evals.app, ["collect"])
    assert result.exit_code != 0
    assert "--all" in result.output


def test_run_agent_uses_no_tracing_and_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        seen["command"], seen["kwargs"] = command, kwargs
        Path(command[command.index("--record") + 1]).write_text("{}")
        return type("Done", (), {"returncode": 0, "stdout": "out", "stderr": ""})()

    monkeypatch.setattr(run_evals.subprocess, "run", fake_run)
    assert run_evals.run_agent(ACME, tmp_path) is True
    command = seen["command"]
    assert command[:3] == ["uv", "run", str(run_evals.REPO_ROOT / "starter_agent.py")]
    assert {"--brief", "--no-tracing"} <= set(command)
    assert command[-1] == "Acme"
    assert seen["kwargs"]["timeout"] == run_evals.AGENT_TIMEOUT_S
    assert (tmp_path / "acme.console.log").read_text() == "out"


def test_run_agent_reports_failure_when_no_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        run_evals.subprocess,
        "run",
        lambda *_a, **_k: type(
            "Done", (), {"returncode": 1, "stdout": "", "stderr": "e"}
        )(),
    )
    assert run_evals.run_agent(ACME, tmp_path) is False


@pytest.mark.parametrize(
    ("j1", "q_mean", "expected"),
    [(1.0, 4.5, True), (0.85, 4.5, False), (1.0, 3.9, False)],
)
def test_pass_rule(j1: float, q_mean: float, expected: bool) -> None:
    scores = run_evals.score_one(record(), ACME, None) | {
        "judge": judge_result(j1, q_mean)
    }
    assert run_evals.passed(scores) is expected


def test_judge_errors_are_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: Any) -> None:
        raise OutputParserException("bad json")

    monkeypatch.setattr(run_evals, "judge_record", broken)
    scores = run_evals.score_one(record(), ACME, llm=object())
    assert scores["judge_error"].startswith("bad json")
    assert scores["pass"] is False


def write_records(tmp_path: Path) -> Path:
    (tmp_path / "acme.record.json").write_text(json.dumps(record()))
    (tmp_path / "stray.record.json").write_text(
        json.dumps(record() | {"input": "Stray"})
    )
    golden = tmp_path / "g.toml"
    golden.write_text(
        '[[company]]\nname = "Acme"\nticker = "ACMX"\nprimary_domains = ["acme.com"]\n'
    )
    return golden


def test_score_skip_judge_writes_report_without_bedrock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    golden = write_records(tmp_path)
    monkeypatch.setattr(run_evals, "build_judge_llm", lambda: pytest.fail("no judge"))
    result = CliRunner().invoke(
        run_evals.app,
        ["score", str(tmp_path), "--golden-set", str(golden), "--skip-judge"],
    )
    assert result.exit_code == 0, result.output
    report = (tmp_path / "report.md").read_text()
    assert "| Acme | FAIL | ok | ok | ok | ok | ok | ok | n/a |" in report
    assert "Stray" not in report
    assert (
        (tmp_path / "scores.csv")
        .read_text()
        .splitlines()[0]
        .startswith("company,pass,D1")
    )
    assert json.loads((tmp_path / "acme.scores.json").read_text())["pass"] is False


def test_score_with_judge_passes_good_brief(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    golden = write_records(tmp_path)
    monkeypatch.setattr(run_evals, "build_judge_llm", lambda: object())
    monkeypatch.setattr(run_evals, "judge_record", lambda *_a: judge_result())
    result = CliRunner().invoke(
        run_evals.app, ["score", str(tmp_path), "--golden-set", str(golden)]
    )
    assert result.exit_code == 0, result.output
    report = (tmp_path / "report.md").read_text()
    assert "| Acme | PASS |" in report
    assert "- Q usefulness: 5 — good" in report


def test_score_fails_on_empty_directory(tmp_path: Path) -> None:
    result = CliRunner().invoke(run_evals.app, ["score", str(tmp_path), "--skip-judge"])
    assert result.exit_code != 0
