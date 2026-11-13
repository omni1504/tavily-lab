# `--brief` eval scoring criteria

This file is the reference for what the eval framework measures. The deterministic checks are implemented in `scoring.py`; the LLM judge checks are in `judge.py`. **Keep this file in sync when criteria change.** All pass bars are drafts, to be tuned after the first runs.

## Inputs

Each company in `golden_set.toml` is run once with:

```
starter_agent.py --brief <name> --no-tracing --record <file>
```

The JSON record contains:
- the brief text;
- every Tavily call: its arguments, plus each result's URL, title, content, publication date and score;
- the URLs Tavily returned.

Scoring works only from this record, so a brief can be re-scored without running the agent or spending Tavily credits.

**Claims** are the bullet lines (`- …`) and table body rows (the persona table) under each `##` section heading. Header text and table header rows are not claims.

## A. Deterministic checks (code, no LLM)

| ID | Check | What it measures | Pass bar |
|---|---|---|---|
| D1 | Structure | All five sections are present, plus the `### Sales` and `### Technical` subsections under talking points. Headings match by prefix, ignoring case, so `Recent News (since …)` counts. | All present |
| D2 | Citation coverage | Share of claims that contain a link or `(No citation)`. | 100% |
| D3 | Citation provenance | Cited URLs that Tavily never returned (same check as the brief's "Unverified citations" list). | 0 |
| D4 | News window | Every Recent news item has a date (ISO `2026-11-05` or `Nov 5, 2026`) on or after the record date − 90 days. Undated items fail. An "Insufficient public data" line is exempt. | 100% |
| D5 | Query hygiene | News queries contain the ticker for public companies. No query contains time words (`latest`, `recent`, or a year), because `start_date` sets the window. | No problems |
| D6 | Primary-source share | Per section: share of cited URLs on the company's `primary_domains`, or on `sec.gov` for public companies. | Reported only |
| D7 | No-citation rate | Per section: share of claims marked `(No citation)`. Talking points are expected to be high. | ≤ 10% in Overview, News, Strategy, Personas |

**Not scored:** the search cap is enforced in code (`ToolCallLimitMiddleware`) and covered by unit tests. The report still shows Tavily calls and credits (advanced = 2, basic = 1) for cost tracking.

## B. LLM judge: source correctness (per claim)

For each cited claim, the judge gets the claim text plus the Tavily title, content and publication date of each URL the claim cites. It judges only from that text; it doesn't open the page. Related issues: #4 and #5.

| ID | Question | Labels | Metric |
|---|---|---|---|
| J1 | **Support:** does the cited source text support the claim? | `supported`, `partial`, `unsupported`, `insufficient_text` | % `supported` (and % `supported` + `partial`) |
| J2 | **Subject:** is the account the main subject of the cited source? | `main`, `mentioned`, `unrelated` | % `main` for Overview and Recent news |
| J3 | **Event date** (Recent news only): does the date in the brief match the event date stated in the source text? | `event_date`, `publication_date`, `wrong`, `not_stated` | % `event_date` |

Claims marked `(No citation)`, and claims citing only URLs that Tavily never returned (D3 failures), are not sent to the judge.

## C. LLM judge: section quality (per brief, 1–5 with a one-line rationale)

| ID | Criterion |
|---|---|
| Q1 | **Reference facts:** does the brief agree with the golden set's `reference_facts`? Contradictions score low. |
| Q2 | **Overview completeness:** business, industry, size, headquarters, products. |
| Q3 | **Personas relevance:** real, current, decision-relevant people, covering both business and technical roles. |
| Q4 | **Talking points grounding:** every point traces to facts in the brief, with no new facts introduced. |
| Q5 | **Usefulness:** is it actionable separately for a Sales Rep and for a Technical Presales engineer? |

## Aggregation and pass rule

- **Per company:** D1–D5 pass or fail, D6/D7 rates, J1–J3 label percentages, and Q1–Q5 scores with their mean.
- **Overall:** the mean of each metric across companies.
- **A company passes when:**
  - D1–D5 all pass;
  - J1 `supported` ≥ 90%;
  - J2 `main` ≥ 80% for news claims;
  - the mean of Q1–Q5 ≥ 4.

## Judge configuration

- **Model:** the same Bedrock model, region and AWS profile as the agent (read from `starter_agent.llm`).
- **Thinking:** off, because structured output uses a forced tool call, which doesn't work with thinking.
- **Calls:** one call per section for J1–J3, and one call per brief for Q1–Q5.
- **Tracing:** off for judge calls.
