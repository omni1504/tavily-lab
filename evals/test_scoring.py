"""Tests for the deterministic eval checks (no network)."""

from pathlib import Path
from typing import Any

import pytest
import scoring
from scoring import Company

ACME = Company("Acme", "ACMX", ("acme.com",), ("CEO: Jane Doe",))
PRIVATE = Company("Privco", None, ("privco.io",), ())

ANSWER = """Intro text that is not a claim.

## Overview
- Acme makes widgets [About](https://acme.com/about)
- Founded in 1999 [Wiki](https://en.wikipedia.org/wiki/Acme)

## Recent News (since 2026-08-15)
- **2026-11-01** — Acme launched X [PR](https://acme.com/pr/x)
- **Nov 3, 2026** — Acme filed results [10-Q](https://www.sec.gov/acme-10q)
- **2026-01-02** — Old item [Old](https://news.example/old)
- Undated item [N](https://news.example/n)

## Strategic Priorities
- Grow AI revenue [About](https://acme.com/about)

## Main Personas
| Name | Title | Relevance | Source |
|---|---|---|---|
| Jane Doe | CEO | Decision-maker | [About](https://acme.com/about) |
| John Roe | CTO | Technical buyer | (No citation) |

## Suggested Talking Points
### Sales
- Pitch value (No citation)
### Technical
- Integrate APIs (No citation)
"""


def record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "input": "Acme",
        "brief": True,
        "date": "2026-11-13",
        "answer": ANSWER,
        "searches": [
            {"args": {"query": "Acme ACMX", "topic": "news"}, "results": []},
            {
                "args": {"query": "Acme overview", "search_depth": "advanced"},
                "results": [],
            },
        ],
        "sources": {
            "https://acme.com/about/": "About",
            "https://en.wikipedia.org/wiki/Acme": "Wiki",
            "https://acme.com/pr/x": "PR",
            "https://www.sec.gov/acme-10q": "10-Q",
            "https://news.example/old": "Old",
            "https://news.example/n": "N",
        },
    }
    return base | overrides


def test_golden_set_loads_five_companies() -> None:
    companies = scoring.load_golden_set(Path(__file__).parent / "golden_set.toml")
    assert [c.name for c in companies] == [
        "Nebius",
        "Amazon",
        "Snowflake",
        "Cisco",
        "Databricks",
    ]
    assert companies[-1].ticker is None
    assert all(c.primary_domains for c in companies)


def test_golden_set_rejects_window_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "g.toml"
    path.write_text('[settings]\nnews_window_days = 30\n[[company]]\nname = "X"\n')
    with pytest.raises(ValueError, match="news_window_days=30"):
        scoring.load_golden_set(path)


def test_extract_claims_reads_bullets_and_table_rows_but_not_headers() -> None:
    claims = scoring.extract_claims(ANSWER)
    by_section = {s: [c for c in claims if c.section == s] for s in scoring.SECTIONS}
    assert len(by_section["Overview"]) == 2
    assert len(by_section["Recent news"]) == 4
    assert [c.text.split("|")[1].strip() for c in by_section["Main personas"]] == [
        "Jane Doe",
        "John Roe",
    ]
    assert by_section["Main personas"][1].no_citation
    assert by_section["Overview"][0].urls == ("https://acme.com/about",)


def test_structure_passes_and_reports_missing_parts() -> None:
    assert scoring.check_structure(ANSWER) == {"pass": True, "missing": []}
    broken = ANSWER.replace("## Main Personas", "## People").replace(
        "### Technical", ""
    )
    result = scoring.check_structure(broken)
    assert result["pass"] is False
    assert result["missing"] == ["Main personas", "### Technical"]


def test_citation_coverage_flags_bare_claims() -> None:
    claims = scoring.extract_claims(ANSWER + "\n- Bare claim with no source\n")
    result = scoring.check_citation_coverage(claims)
    assert result["pass"] is False
    assert result["uncovered"] == ["- Bare claim with no source"]
    assert scoring.check_citation_coverage([])["pass"] is False


def test_provenance_flags_urls_tavily_never_returned() -> None:
    claims = scoring.extract_claims(ANSWER)
    assert scoring.check_provenance(claims, record())["pass"] is True
    sources = dict(record()["sources"])
    del sources["https://acme.com/pr/x"]
    result = scoring.check_provenance(claims, record(sources=sources))
    assert result == {"pass": False, "unverified": ["https://acme.com/pr/x"]}


def test_news_window_flags_old_and_undated_items() -> None:
    result = scoring.check_news_window(scoring.extract_claims(ANSWER), record())
    assert result["pass"] is False
    assert [t[:20] for t in result["out_of_window"]] == ["- **2026-01-02** — O"]
    assert result["undated"] == ["- Undated item [N](https://news.example/n)"]


def test_news_window_exempts_insufficient_data_line() -> None:
    answer = "## Recent news\n- Insufficient public data (No citation)\n"
    result = scoring.check_news_window(scoring.extract_claims(answer), record())
    assert result["pass"] is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("**2026-11-05** — x", "2026-11-05"),
        ("**Nov 3, 2026** — x", "2026-11-03"),
        ("September 30, 2026 – x", "2026-09-30"),
        ("no date", None),
    ],
)
def test_parse_item_date(text: str, expected: str | None) -> None:
    parsed = scoring.parse_item_date(text)
    assert (parsed.isoformat() if parsed else None) == expected


def test_query_hygiene_flags_time_words_and_missing_ticker() -> None:
    assert scoring.check_query_hygiene(record(), ACME)["pass"] is True
    bad = record(
        searches=[
            {"args": {"query": "Acme latest news 2026", "topic": "news"}},
            {"args": {"query": "Acme recent strategy"}},
        ]
    )
    problems = scoring.check_query_hygiene(bad, ACME)["problems"]
    assert len(problems) == 3
    assert any("without ticker ACMX" in p for p in problems)


def test_query_hygiene_needs_no_ticker_for_private_company() -> None:
    searches = [{"args": {"query": "Privco", "topic": "news"}}]
    assert scoring.check_query_hygiene(record(searches=searches), PRIVATE)["pass"]


def test_primary_share_counts_company_domains_and_sec_for_public() -> None:
    assert scoring.is_primary("https://ir.acme.com/x", ACME)
    assert scoring.is_primary("https://www.sec.gov/x", ACME)
    assert not scoring.is_primary("https://www.sec.gov/x", PRIVATE)
    assert not scoring.is_primary("https://notacme.com/x", ACME)
    rates = scoring.section_rates(scoring.extract_claims(ANSWER), ACME)
    assert rates["Overview"]["primary_share"] == 0.5
    assert rates["Recent news"]["primary_share"] == 0.5


def test_no_citation_rate_limits_factual_sections_only() -> None:
    rates = scoring.section_rates(scoring.extract_claims(ANSWER), ACME)
    result = scoring.check_no_citation_rate(rates)
    assert result == {"pass": False, "over_limit": {"Main personas": 0.5}}
    assert rates["Suggested talking points"]["no_citation_rate"] == 1.0


def test_search_cost_counts_advanced_as_two_credits() -> None:
    assert scoring.search_cost(record()) == {"searches": 2, "credits": 3}


def test_score_deterministic_returns_all_checks() -> None:
    scores = scoring.score_deterministic(record(), ACME)
    assert set(scores) == {
        "D1_structure",
        "D2_citation_coverage",
        "D3_provenance",
        "D4_news_window",
        "D5_query_hygiene",
        "D6_primary_share",
        "D7_no_citation_rate",
        "section_rates",
        "cost",
    }


def test_nested_sub_bullets_fold_into_parent_claim() -> None:
    answer = (
        "## Overview\n"
        "- **Products:** platform encompassing:\n"
        "  - **A** – first\n"
        "  - **B** – second [Src](https://acme.com/p)\n"
        "- Next claim (No citation)\n"
    )
    claims = scoring.extract_claims(answer)
    assert len(claims) == 2
    assert claims[0].text.endswith("[Src](https://acme.com/p)")
    assert claims[0].urls == ("https://acme.com/p",)
    assert scoring.check_citation_coverage(claims)["pass"] is True
