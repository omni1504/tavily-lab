# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "langchain>=1.0.0",
#   "langchain-aws>=1.7.6",
#   "langchain-tavily>=0.2.0",
#   "python-dotenv>=1.0.0",
#   "rich>=13.0.0",
#   "typer>=0.12.0",
# ]
# ///
"""Eval runner for `starter_agent.py --brief` (criteria: evals/SCORING.md).

  uv run evals/run_evals.py collect --companies Databricks   # runs the agent (spends Tavily credits)
  uv run evals/run_evals.py collect --all
  uv run evals/run_evals.py score evals/results/<run>         # judge only, no agent/Tavily calls

`collect` and `score` are separate so criteria can be iterated without re-running the agent.
Everything stays local: agent runs use --no-tracing and judge calls run with tracing off.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from botocore.exceptions import BotoCoreError, ClientError
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
# Keep judge calls local; LangSmith integration is tracked as a separate issue.
os.environ["LANGSMITH_TRACING"] = "false"

from judge import build_judge_llm, judge_record
from scoring import Company, load_golden_set, score_deterministic

DEFAULT_GOLDEN_SET = EVALS_DIR / "golden_set.toml"
RESULTS_DIR = EVALS_DIR / "results"
AGENT_TIMEOUT_S = 900
PASS_J1 = 0.90
PASS_J2_NEWS = 0.80
PASS_Q_MEAN = 4.0
DETERMINISTIC_GATES = (
    "D1_structure",
    "D2_citation_coverage",
    "D3_provenance",
    "D4_news_window",
    "D5_query_hygiene",
)

JUDGE_ERRORS = (
    BotoCoreError,
    ClientError,
    OutputParserException,
    ValidationError,
)

app = typer.Typer(add_completion=False, help=__doc__)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def select_companies(
    companies: list[Company], names: list[str] | None, run_all: bool
) -> list[Company]:
    """Refuse to run without an explicit selection, so credits are never spent by accident."""
    if run_all == bool(names):
        raise typer.BadParameter("pass either --companies NAME ... or --all")
    if run_all:
        return companies
    by_name = {c.name.lower(): c for c in companies}
    unknown = [n for n in names or [] if n.lower() not in by_name]
    if unknown:
        raise typer.BadParameter(f"not in golden set: {', '.join(unknown)}")
    return [by_name[n.lower()] for n in names or []]


def run_agent(company: Company, out_dir: Path) -> bool:
    record_path = out_dir / f"{slug(company.name)}.record.json"
    command = [
        "uv",
        "run",
        str(REPO_ROOT / "starter_agent.py"),
        "--brief",
        "--no-tracing",
        "--record",
        str(record_path),
        company.name,
    ]
    # Fixed argv (no shell); the company name comes from the golden set file.
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=AGENT_TIMEOUT_S,
        check=False,
    )
    log = out_dir / f"{slug(company.name)}.console.log"
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    return result.returncode == 0 and record_path.exists()


@app.command()
def collect(
    companies: Annotated[
        list[str] | None,
        typer.Option("--companies", help="Golden-set company names to run."),
    ] = None,
    run_all: Annotated[
        bool, typer.Option("--all", help="Run every company in the golden set.")
    ] = False,
    golden_set: Annotated[
        Path, typer.Option(help="Golden set TOML.")
    ] = DEFAULT_GOLDEN_SET,
) -> None:
    """Run the agent for selected companies and save their records (spends Tavily credits)."""
    selected = select_companies(load_golden_set(golden_set), companies, run_all)
    out_dir = RESULTS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Sequential on purpose (credit and rate-limit safety). Consider a --concurrency option
    # (e.g. a ThreadPoolExecutor over run_agent) once larger golden sets make runs slow.
    for company in selected:
        typer.echo(f"collect {company.name} ...")
        ok = run_agent(company, out_dir)
        typer.echo(f"  {'ok' if ok else 'FAILED (see console.log)'}")
    typer.echo(f"records in {out_dir}")


def passed(scores: dict[str, Any]) -> bool:
    det, judged = scores["deterministic"], scores.get("judge")
    if not all(det[k]["pass"] for k in DETERMINISTIC_GATES) or not judged:
        return False
    j1, j2 = judged["J"]["J1_supported"], judged["J"]["J2_main_subject_news"]
    return (
        j1 is not None
        and j1 >= PASS_J1
        and (j2 is None or j2 >= PASS_J2_NEWS)
        and judged["Q_mean"] >= PASS_Q_MEAN
    )


def score_one(
    record: dict[str, Any], company: Company, llm: Any | None
) -> dict[str, Any]:
    scores: dict[str, Any] = {
        "company": company.name,
        "deterministic": score_deterministic(record, company),
    }
    if llm is not None:
        try:
            scores["judge"] = judge_record(llm, record, company)
        except JUDGE_ERRORS as exc:  # report and continue with the other companies
            typer.echo(f"  judge failed for {company.name}: {exc}", err=True)
            scores["judge_error"] = str(exc)
    scores["pass"] = passed(scores)
    return scores


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def summary_row(scores: dict[str, Any]) -> dict[str, str]:
    det, judged = scores["deterministic"], scores.get("judge") or {}
    j = judged.get("J", {})
    row = {"company": scores["company"], "pass": "PASS" if scores["pass"] else "FAIL"}
    row |= {
        k.split("_")[0]: "ok" if det[k]["pass"] else "x" for k in DETERMINISTIC_GATES
    }
    row |= {
        "D7": "ok" if det["D7_no_citation_rate"]["pass"] else "x",
        "J1": fmt(j.get("J1_supported")),
        "J2_news": fmt(j.get("J2_main_subject_news")),
        "J3": fmt(j.get("J3_event_date")),
        "Q_mean": f"{judged['Q_mean']:.1f}" if judged else "n/a",
        "searches": str(det["cost"]["searches"]),
        "credits": str(det["cost"]["credits"]),
    }
    return row


def write_report(out_dir: Path, all_scores: list[dict[str, Any]]) -> None:
    rows = [summary_row(s) for s in all_scores]
    with (out_dir / "scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    header = "| " + " | ".join(rows[0]) + " |"
    lines = [f"# Brief eval report ({out_dir.name})", "", header]
    lines.append("|" + "---|" * len(rows[0]))
    lines += ["| " + " | ".join(r.values()) + " |" for r in rows]
    lines += ["", "Criteria: evals/SCORING.md. Details: <company>.scores.json.", ""]
    for scores in all_scores:
        lines += report_details(scores)
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def report_details(scores: dict[str, Any]) -> list[str]:
    """Only what failed, so the report stays short; full detail is in the JSON."""
    det = scores["deterministic"]
    lines = [f"## {scores['company']}"]
    lines += [f"- D1 missing: {m}" for m in det["D1_structure"]["missing"]]
    lines += [f"- D2 uncovered: {c}" for c in det["D2_citation_coverage"]["uncovered"]]
    lines += [f"- D3 unverified: {u}" for u in det["D3_provenance"]["unverified"]]
    news = det["D4_news_window"]
    lines += [f"- D4 out of window: {c}" for c in news["out_of_window"]]
    lines += [f"- D4 undated: {c}" for c in news["undated"]]
    lines += [f"- D5 {p}" for p in det["D5_query_hygiene"]["problems"]]
    lines += [
        f"- D7 over limit: {s} {r:.0%}"
        for s, r in det["D7_no_citation_rate"]["over_limit"].items()
    ]
    if "judge_error" in scores:
        lines.append(f"- judge error: {scores['judge_error']}")
    for claim in (scores.get("judge") or {}).get("claims", []):
        if (
            claim.get("support") not in ("supported", None)
            or claim.get("subject") == "unrelated"
        ):
            lines.append(
                f"- J {claim.get('support')}/{claim.get('subject')}/{claim.get('event_date')}: "
                f"{claim['claim'][:160]} — {claim.get('rationale', '')}"
            )
    for name, q in (scores.get("judge") or {}).get("Q", {}).items():
        lines.append(f"- Q {name}: {q['score']} — {q['rationale']}")
    return [*lines, ""]


@app.command()
def score(
    results_dir: Annotated[
        Path, typer.Argument(help="A directory created by collect.")
    ],
    golden_set: Annotated[
        Path, typer.Option(help="Golden set TOML.")
    ] = DEFAULT_GOLDEN_SET,
    skip_judge: Annotated[
        bool,
        typer.Option(
            "--skip-judge", help="Deterministic checks only (no Bedrock calls)."
        ),
    ] = False,
) -> None:
    """Score saved records (no agent or Tavily calls) and write report.md and scores.csv."""
    by_name = {c.name.lower(): c for c in load_golden_set(golden_set)}
    llm = None if skip_judge else build_judge_llm()
    all_scores: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.record.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        company = by_name.get(str(record.get("input", "")).lower())
        if company is None:
            typer.echo(
                f"skip {path.name}: {record.get('input')!r} not in golden set", err=True
            )
            continue
        typer.echo(f"score {company.name} ...")
        scores = score_one(record, company, llm)
        out = results_dir / f"{slug(company.name)}.scores.json"
        out.write_text(
            json.dumps(scores, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        all_scores.append(scores)
    if not all_scores:
        raise typer.BadParameter(f"no scorable records in {results_dir}")
    write_report(results_dir, all_scores)
    typer.echo(f"report: {results_dir / 'report.md'}")


if __name__ == "__main__":
    app()
