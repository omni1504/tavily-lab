"""Tests for the LLM judge with a fake structured-output model (no Bedrock calls)."""

from typing import Any

import judge
import pytest
from judge import ClaimJudgment, QualityJudgment, Score, SectionJudgment
from scoring import Company

ACME = Company("Acme", "ACMX", ("acme.com",), ("CEO: Jane Doe",))

ANSWER = """## Overview
- Acme makes widgets [About](https://acme.com/about)
- Unsourced view (No citation)
- Invented [X](https://never-returned.example/x)

## Recent news (since 2026-08-15)
- **2026-11-01** — Acme launched X [PR](https://acme.com/pr/x)

## Suggested talking points
### Sales
- Pitch value (No citation)
"""

RECORD: dict[str, Any] = {
    "date": "2026-11-13",
    "answer": ANSWER,
    "searches": [
        {
            "args": {"query": "Acme"},
            "results": [
                {
                    "url": "https://acme.com/about/",
                    "title": "About Acme",
                    "content": "Acme makes widgets. " * 200,
                    "published_date": None,
                },
                {
                    "url": "https://acme.com/pr/x",
                    "title": "Acme launches X",
                    "content": "On Nov 1, 2026 Acme launched X.",
                    "published_date": "2026-11-02",
                },
            ],
        }
    ],
}


class FakeStructuredLLM:
    """Returns canned schema instances and records the prompts it was sent."""

    def __init__(self, responses: dict[type, list[Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[type, list[Any]]] = []

    def with_structured_output(self, schema: type) -> Any:
        llm = self

        class Runner:
            def invoke(self, messages: list[Any]) -> Any:
                llm.calls.append((schema, messages))
                return llm.responses[schema].pop(0)

        return Runner()


def quality(score: int = 4) -> QualityJudgment:
    s = Score(score=score, rationale="ok")
    return QualityJudgment(
        reference_facts=s,
        overview_completeness=s,
        personas_relevance=s,
        talking_points_grounding=s,
        usefulness=s,
    )


def claim(claim_id: int, **labels: str) -> ClaimJudgment:
    base = {
        "support": "supported",
        "subject": "main",
        "event_date": "not_applicable",
        "rationale": "r",
    }
    return ClaimJudgment.model_validate({"claim_id": claim_id} | base | labels)


def test_build_judge_llm_reuses_agent_model_region_and_profile() -> None:
    llm = judge.build_judge_llm()
    agent = judge.starter_agent.llm
    assert (llm.model_id, llm.region_name, llm.credentials_profile_name) == (
        agent.model_id,
        agent.region_name,
        agent.credentials_profile_name,
    )
    assert llm.additional_model_request_fields is None  # no thinking
    assert llm.temperature == 0


def test_only_claims_citing_returned_urls_are_judged() -> None:
    index = judge.source_index(RECORD)
    claims = judge.judgeable(judge.extract_claims(ANSWER), index)
    assert [c.text[:12] for c in claims] == ["- Acme makes", "- **2026-11-"]


def test_format_claims_includes_source_text_capped_and_dates() -> None:
    index = judge.source_index(RECORD)
    claims = judge.judgeable(judge.extract_claims(ANSWER), index)
    text = judge.format_claims(claims, index)
    assert "## Claim 0 (section: Overview)" in text
    assert "Published: unknown" in text
    assert "Published: 2026-11-02" in text
    assert text.count("Acme makes widgets.") < 200  # content truncated
    assert "never-returned" not in text.split("## Claim 1")[1]


def test_judge_record_runs_one_call_per_section_plus_quality() -> None:
    llm = FakeStructuredLLM(
        {
            SectionJudgment: [
                SectionJudgment(judgments=[claim(0)]),
                SectionJudgment(
                    judgments=[
                        claim(0, subject="mentioned", event_date="publication_date")
                    ]
                ),
            ],
            QualityJudgment: [quality(4)],
        }
    )
    result = judge.judge_record(llm, RECORD, ACME)

    assert [schema for schema, _ in llm.calls] == [
        SectionJudgment,
        SectionJudgment,
        QualityJudgment,
    ]
    assert result["J"] == {
        "J1_supported": 1.0,
        "J1_supported_or_partial": 1.0,
        "J2_main_subject": 0.5,
        "J2_main_subject_news": 0.0,
        "J3_event_date": 0.0,
    }
    assert result["Q_mean"] == 4
    quality_prompt = llm.calls[-1][1][1][1]
    assert "CEO: Jane Doe" in quality_prompt


def test_claims_the_judge_skips_are_marked_not_judged() -> None:
    llm = FakeStructuredLLM(
        {
            SectionJudgment: [
                SectionJudgment(judgments=[]),
                SectionJudgment(judgments=[]),
            ],
            QualityJudgment: [quality(3)],
        }
    )
    result = judge.judge_record(llm, RECORD, ACME)
    assert all(c.get("error") == "not judged" for c in result["claims"])
    assert result["J"]["J1_supported"] is None


@pytest.mark.parametrize("score", [0, 6])
def test_quality_scores_are_bounded(score: int) -> None:
    with pytest.raises(ValueError):
        Score(score=score, rationale="x")
