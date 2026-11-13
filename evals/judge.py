"""LLM-as-a-judge for `--brief` records: source correctness (J1-J3) and section quality (Q1-Q5).

Criteria are documented in evals/SCORING.md. The judge only sees the text Tavily returned for
each cited URL (from the run record); it never browses, so labels are reproducible offline.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel, Field
from scoring import SECTIONS, Claim, Company, extract_claims

import starter_agent
from starter_agent import normalize_url

# Tavily snippets are ~2.4k chars at most; the cap only guards against unusual payloads, so the
# judge sees the same text the agent saw when writing the brief.
SOURCE_CHAR_LIMIT = 6000
JUDGE_MAX_TOKENS = 8192
SUBJECT_SECTIONS = ("Overview", "Recent news")

JUDGE_SYSTEM_PROMPT = """You are a strict fact-checking judge for account research briefs.
Judge ONLY from the source text provided with each claim. Do not use outside knowledge.

For every claim, return:
- support: "supported" if the source text states the claim; "partial" if only part of it;
  "unsupported" if the text does not back it or contradicts it; "insufficient_text" if the
  provided text is too short or truncated to decide.
- subject: "main" if the account is the main subject of the source (judge from title and
  text); "mentioned" if the account is only mentioned; "unrelated" if it is about something else.
- event_date: only for Recent news claims. "event_date" if the date in the claim matches when
  the event happened according to the text; "publication_date" if the claim uses the article's
  publication date instead of a different event date stated in the text; "wrong" if it matches
  neither; "not_stated" if the text gives no event date. Use "not_applicable" for other sections.
- rationale: one short sentence.
For Main personas table rows, judge support only for the person's name and title; the
Relevance column is the writer's own analysis and must not lower the support label.
Return exactly one judgment per claim id.
"""

QUALITY_SYSTEM_PROMPT = """You are an expert reviewer of account briefs written for a Sales
Representative and a Technical Presales engineer. Score each criterion from 1 (poor) to 5
(excellent) with a one-sentence rationale:
- Q1 reference_facts: agreement with the reference facts given (contradictions score 1-2).
- Q2 overview_completeness: business, industry, size, headquarters, products are covered.
- Q3 personas_relevance: real, current, decision-relevant people; business and technical roles.
- Q4 talking_points_grounding: every talking point traces to facts stated in the brief.
- Q5 usefulness: actionable separately for Sales and for Technical Presales.
"""


class ClaimJudgment(BaseModel):
    claim_id: int
    support: Literal["supported", "partial", "unsupported", "insufficient_text"]
    subject: Literal["main", "mentioned", "unrelated"]
    event_date: Literal[
        "event_date", "publication_date", "wrong", "not_stated", "not_applicable"
    ]
    rationale: str


class SectionJudgment(BaseModel):
    judgments: list[ClaimJudgment]


class Score(BaseModel):
    score: int = Field(ge=1, le=5)
    rationale: str


class QualityJudgment(BaseModel):
    reference_facts: Score
    overview_completeness: Score
    personas_relevance: Score
    talking_points_grounding: Score
    usefulness: Score


def build_judge_llm() -> ChatBedrockConverse:
    """Same model/region/profile as the agent; no thinking, because structured output forces a tool call."""
    agent_llm = starter_agent.llm
    return ChatBedrockConverse(
        model_id=agent_llm.model_id,
        region_name=agent_llm.region_name,
        credentials_profile_name=agent_llm.credentials_profile_name,
        max_tokens=JUDGE_MAX_TOKENS,
        temperature=0,
    )


def source_index(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Tavily results keyed by normalized URL, as returned during the run.

    Tavily returns query-specific snippets, so one URL can come back from several searches
    with different text; all snippets are merged so the judge sees everything the agent saw.
    """
    index: dict[str, dict[str, Any]] = {}
    for search in record.get("searches", []):
        for result in search.get("results", []):
            if not result.get("url"):
                continue
            key = normalize_url(result["url"])
            content = str(result.get("content") or "")
            if key not in index:
                index[key] = dict(result, content=content)
            elif content and content not in index[key]["content"]:
                index[key]["content"] += f"\n[...]\n{content}"
    return index


def judgeable(claims: list[Claim], index: dict[str, dict[str, Any]]) -> list[Claim]:
    """Claims with at least one cited URL that Tavily returned (others are covered by D2/D3)."""
    return [c for c in claims if any(url in index for url in c.urls)]


def format_claims(claims: list[Claim], index: dict[str, dict[str, Any]]) -> str:
    blocks: list[str] = []
    for claim_id, claim in enumerate(claims):
        sources = [index[url] for url in claim.urls if url in index]
        lines = [f"## Claim {claim_id} (section: {claim.section})", claim.text]
        for source in sources:
            lines += [
                f"### Source: {source.get('title', 'Untitled')}",
                f"URL: {source.get('url', '')}",
                f"Published: {source.get('published_date') or 'unknown'}",
                str(source.get("content", ""))[:SOURCE_CHAR_LIMIT],
            ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def judge_section(
    llm: Any, company: Company, claims: list[Claim], index: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    judge = llm.with_structured_output(SectionJudgment)
    result: SectionJudgment = judge.invoke(
        [
            ("system", JUDGE_SYSTEM_PROMPT),
            ("human", f"Account: {company.name}\n\n{format_claims(claims, index)}"),
        ]
    )
    by_id = {j.claim_id: j for j in result.judgments}
    return [
        {"section": c.section, "claim": c.text}
        | (
            by_id[i].model_dump(exclude={"claim_id"})
            if i in by_id
            else {"error": "not judged"}
        )
        for i, c in enumerate(claims)
    ]


def judge_quality(llm: Any, company: Company, answer: str) -> dict[str, Any]:
    facts = (
        "\n".join(f"- {fact}" for fact in company.reference_facts) or "- (none given)"
    )
    judge = llm.with_structured_output(QualityJudgment)
    result: QualityJudgment = judge.invoke(
        [
            ("system", QUALITY_SYSTEM_PROMPT),
            (
                "human",
                f"Account: {company.name}\nReference facts:\n{facts}\n\nBrief:\n{answer}",
            ),
        ]
    )
    return result.model_dump()


def share(
    items: list[dict[str, Any]], key: str, labels: tuple[str, ...]
) -> float | None:
    judged = [i for i in items if key in i]
    return sum(i[key] in labels for i in judged) / len(judged) if judged else None


def aggregate_claims(judgments: list[dict[str, Any]]) -> dict[str, float | None]:
    news = [j for j in judgments if j["section"] == "Recent news"]
    subject_claims = [j for j in judgments if j["section"] in SUBJECT_SECTIONS]
    return {
        "J1_supported": share(judgments, "support", ("supported",)),
        "J1_supported_or_partial": share(
            judgments, "support", ("supported", "partial")
        ),
        "J2_main_subject": share(subject_claims, "subject", ("main",)),
        "J2_main_subject_news": share(news, "subject", ("main",)),
        "J3_event_date": share(news, "event_date", ("event_date",)),
    }


def judge_record(llm: Any, record: dict[str, Any], company: Company) -> dict[str, Any]:
    """Run J1-J3 (one call per section with judgeable claims) and Q1-Q5 (one call)."""
    answer = record.get("answer", "")
    index = source_index(record)
    claims = judgeable(extract_claims(answer), index)
    judgments: list[dict[str, Any]] = []
    for section in SECTIONS:
        in_section = [c for c in claims if c.section == section]
        if in_section:
            judgments += judge_section(llm, company, in_section, index)
    quality = judge_quality(llm, company, answer)
    scores = [q["score"] for q in quality.values()]
    return {
        "claims": judgments,
        "J": aggregate_claims(judgments),
        "Q": quality,
        "Q_mean": sum(scores) / len(scores),
    }
