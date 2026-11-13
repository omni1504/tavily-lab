"""Deterministic checks (D1-D7) for `--brief` run records, plus claim extraction for the judge.

The scoring criteria (what each check measures, pass bars, and how they combine with the
judge's J/Q scores) are documented in evals/SCORING.md. Keep that file in sync with this one.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from starter_agent import BRIEF_NEWS_WINDOW_DAYS, URL_PATTERN, normalize_url

SECTIONS = (
    "Overview",
    "Recent news",
    "Strategic priorities",
    "Main personas",
    "Suggested talking points",
)
FACTUAL_SECTIONS = SECTIONS[:4]
TALKING_POINT_SUBSECTIONS = ("Sales", "Technical")
NO_CITATION = "(No citation)"
INSUFFICIENT = "Insufficient public data"
MAX_NO_CITATION_RATE = 0.10
TIME_WORDS = re.compile(r"\b(latest|recent|(?:19|20)\d{2})\b", re.IGNORECASE)
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
TEXT_DATE = re.compile(r"\b([A-Z][a-z]{2,8})\.? (\d{1,2}), (\d{4})\b")
TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")


@dataclass(frozen=True)
class Company:
    name: str
    ticker: str | None
    primary_domains: tuple[str, ...]
    reference_facts: tuple[str, ...]


@dataclass(frozen=True)
class Claim:
    section: str
    text: str
    urls: tuple[str, ...]

    @property
    def no_citation(self) -> bool:
        return NO_CITATION.lower() in self.text.lower()


def load_golden_set(path: Path) -> list[Company]:
    """Load companies; a window mismatch would silently score news against the wrong dates."""
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    window = config.get("settings", {}).get("news_window_days", BRIEF_NEWS_WINDOW_DAYS)
    if window != BRIEF_NEWS_WINDOW_DAYS:
        raise ValueError(
            f"news_window_days={window} in {path} does not match the agent "
            f"({BRIEF_NEWS_WINDOW_DAYS})"
        )
    return [
        Company(
            name=entry["name"],
            ticker=entry.get("ticker"),
            primary_domains=tuple(entry.get("primary_domains", [])),
            reference_facts=tuple(entry.get("reference_facts", [])),
        )
        for entry in config.get("company", [])
    ]


def canonical_section(heading: str) -> str | None:
    """Map a model-written heading (any case, optional suffix like dates) to a section."""
    lowered = heading.strip().lower()
    return next((s for s in SECTIONS if lowered.startswith(s.lower())), None)


def split_sections(answer: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in answer.splitlines():
        if line.startswith("## "):
            current = canonical_section(line[3:])
            if current:
                sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return sections


def _claim_lines(lines: list[str]) -> list[str]:
    """Bullets and table body rows; table header rows sit directly above the separator."""
    claims: list[str] = []
    previous_was_table_row = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("|") and TABLE_SEPARATOR.match(line):
            if previous_was_table_row and claims:
                claims.pop()  # the header row
            previous_was_table_row = False
            continue
        is_table_row = line.startswith("|")
        if is_table_row or line.startswith(("- ", "* ")):
            claims.append(line)
        previous_was_table_row = is_table_row
    return claims


def extract_claims(answer: str) -> list[Claim]:
    return [
        Claim(
            section=section,
            text=line,
            urls=tuple(
                dict.fromkeys(normalize_url(u) for u in URL_PATTERN.findall(line))
            ),
        )
        for section, lines in split_sections(answer).items()
        for line in _claim_lines(lines)
    ]


def check_structure(answer: str) -> dict[str, Any]:
    """D1: all sections, and Sales/Technical under talking points."""
    sections = split_sections(answer)
    missing = [s for s in SECTIONS if s not in sections]
    talking = "\n".join(sections.get("Suggested talking points", []))
    missing += [
        f"### {sub}"
        for sub in TALKING_POINT_SUBSECTIONS
        if not re.search(rf"^###\s+{sub}\b", talking, re.MULTILINE | re.IGNORECASE)
    ]
    return {"pass": not missing, "missing": missing}


def check_citation_coverage(claims: list[Claim]) -> dict[str, Any]:
    """D2: every claim carries a link or an explicit (No citation)."""
    uncovered = [c.text for c in claims if not c.urls and not c.no_citation]
    rate = 1 - len(uncovered) / len(claims) if claims else 0.0
    return {
        "pass": bool(claims) and not uncovered,
        "rate": rate,
        "uncovered": uncovered,
    }


def check_provenance(claims: list[Claim], record: dict[str, Any]) -> dict[str, Any]:
    """D3: cited URLs must be ones Tavily actually returned."""
    known = {normalize_url(url) for url in record.get("sources", {})}
    cited = dict.fromkeys(url for c in claims for url in c.urls)
    unverified = [url for url in cited if url not in known]
    return {"pass": not unverified, "unverified": unverified}


def parse_item_date(text: str) -> date | None:
    if match := ISO_DATE.search(text):
        return date.fromisoformat(match.group(1))
    if match := TEXT_DATE.search(text):
        month, day, year = match.groups()
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f"{month} {day} {year}", fmt).date()
            except ValueError:
                continue
    return None


def check_news_window(claims: list[Claim], record: dict[str, Any]) -> dict[str, Any]:
    """D4: news items carry a date inside the window (undated items count as failures)."""
    since = date.fromisoformat(record["date"]) - timedelta(days=BRIEF_NEWS_WINDOW_DAYS)
    out_of_window: list[str] = []
    undated: list[str] = []
    for claim in claims:
        if claim.section != "Recent news" or INSUFFICIENT in claim.text:
            continue
        item_date = parse_item_date(claim.text)
        if item_date is None:
            undated.append(claim.text)
        elif item_date < since:
            out_of_window.append(claim.text)
    passed = not out_of_window and not undated
    return {"pass": passed, "out_of_window": out_of_window, "undated": undated}


def check_query_hygiene(record: dict[str, Any], company: Company) -> dict[str, Any]:
    """D5: ticker in news queries for public companies; no time words in any query."""
    problems: list[str] = []
    for search in record.get("searches", []):
        args = search.get("args", {})
        query = str(args.get("query", ""))
        if TIME_WORDS.search(query):
            problems.append(f"time word in query: {query!r}")
        has_ticker = company.ticker and re.search(
            rf"\b{re.escape(company.ticker)}\b", query, re.IGNORECASE
        )
        if args.get("topic") == "news" and company.ticker and not has_ticker:
            problems.append(f"news query without ticker {company.ticker}: {query!r}")
    return {"pass": not problems, "problems": problems}


def is_primary(url: str, company: Company) -> bool:
    host = (urlparse(url).hostname or "").lower()
    domains = list(company.primary_domains) + (["sec.gov"] if company.ticker else [])
    return any(host == d or host.endswith(f".{d}") for d in domains)


def section_rates(claims: list[Claim], company: Company) -> dict[str, dict[str, float]]:
    """D6/D7 inputs: per-section primary-source share and (No citation) rate."""
    rates: dict[str, dict[str, float]] = {}
    for section in SECTIONS:
        in_section = [c for c in claims if c.section == section]
        urls = [u for c in in_section for u in c.urls]
        rates[section] = {
            "claims": len(in_section),
            "primary_share": sum(is_primary(u, company) for u in urls) / len(urls)
            if urls
            else 0.0,
            "no_citation_rate": sum(c.no_citation for c in in_section) / len(in_section)
            if in_section
            else 0.0,
        }
    return rates


def check_no_citation_rate(rates: dict[str, dict[str, float]]) -> dict[str, Any]:
    """D7: factual sections should rarely fall back to (No citation)."""
    over = {
        s: rates[s]["no_citation_rate"]
        for s in FACTUAL_SECTIONS
        if rates[s]["no_citation_rate"] > MAX_NO_CITATION_RATE
    }
    return {"pass": not over, "over_limit": over}


def search_cost(record: dict[str, Any]) -> dict[str, int]:
    """Tavily calls and credits (advanced = 2, basic = 1) for cost tracking, not scoring."""
    searches = record.get("searches", [])
    credits = sum(
        2 if s.get("args", {}).get("search_depth") == "advanced" else 1
        for s in searches
    )
    return {"searches": len(searches), "credits": credits}


def score_deterministic(record: dict[str, Any], company: Company) -> dict[str, Any]:
    answer = record.get("answer", "")
    claims = extract_claims(answer)
    rates = section_rates(claims, company)
    return {
        "D1_structure": check_structure(answer),
        "D2_citation_coverage": check_citation_coverage(claims),
        "D3_provenance": check_provenance(claims, record),
        "D4_news_window": check_news_window(claims, record),
        "D5_query_hygiene": check_query_hygiene(record, company),
        "D6_primary_share": {s: r["primary_share"] for s, r in rates.items()},
        "D7_no_citation_rate": check_no_citation_rate(rates),
        "section_rates": rates,
        "cost": search_cost(record),
    }
