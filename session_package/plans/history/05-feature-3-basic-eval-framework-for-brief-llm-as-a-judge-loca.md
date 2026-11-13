# Feature 3 — Basic eval framework for `--brief` (LLM-as-a-judge, local output)

## Context
`--brief` produces cited account briefs, but quality is only checked by hand. Snowflake runs exposed issues that the code-built appendix can't catch:
- misdated news (publication date used instead of event date);
- a secondary aggregator article whose main subject is another company;
- off-topic search results.

Issues #4 and #5 ask for a golden-set eval. This feature adds a **separate eval program** that:
- runs the real agent on a **configurable golden set** (Nebius, Amazon, Snowflake, Cisco, Databricks);
- scores each brief with **deterministic checks** plus an **LLM judge** that uses the same Bedrock model, region and profile;
- writes results to local files.

There is no LangSmith integration. A follow-up issue tracks connecting the evals to the existing tracing setup.

Branch: `feat/brief-evals`.

## How the eval calls the main agent
The eval runs the agent as a subprocess: `uv run starter_agent.py --brief "<account>" --record <path.json>`. That way it tests the exact production code path.

**New option in `starter_agent.py` (`--record PATH`, needs approval, since it changes the CLI):** after the run, write a JSON record with:
- the account name;
- the brief text;
- every Tavily call: its args, plus each result's url, title, content, published_date and score;
- the appendix lists;
- the run's duration.

This is about 25 lines: a dict built in the existing stream loop, and one `json.dump`. Console output stays the same.

## Layout (new `evals/` folder, self-contained like `parser/`)
- `evals/golden_set.toml`: the configurable company list (stdlib `tomllib`, so no new dependency).
- `evals/run_evals.py`: CLI entry point with PEP 723 inline deps matching `starter_agent.py`. It runs the briefs, scores them and writes the report.
- `evals/scoring.py`: deterministic checks, plus extracting claims and cited URLs from the brief. It reuses `URL_PATTERN`, `normalize_url` and `BRIEF_NEWS_WINDOW_DAYS` from `starter_agent.py`.
- `evals/judge.py`: the LLM judge. It builds its own `ChatBedrockConverse` from `starter_agent.llm`'s `model_id`, `region_name` and `credentials_profile_name`, so the model config is the same. It has **no thinking**, because structured output needs a forced tool call, which is incompatible with thinking. It uses `with_structured_output` with Pydantic models.
- `evals/results/<timestamp>/` (git-ignored) holds:
  - `<company>.record.json`
  - `<company>.scores.json`
  - `report.md` (a scorecard table per company and overall)
  - `scores.csv`
- Tests: `evals/test_scoring.py` and `evals/test_judge.py`, with a fake LLM. No network calls.

### `evals/golden_set.toml` (draft)
```toml
[settings]
news_window_days = 90          # must match the agent
max_searches = 10

[[company]]
name = "Nebius"
ticker = "NBIS"                # omit for private companies
primary_domains = ["nebius.com"]
reference_facts = ["CEO: Arkady Volozh", "Headquarters: Amsterdam, Netherlands"]

[[company]]
name = "Amazon"
ticker = "AMZN"
primary_domains = ["amazon.com", "aboutamazon.com", "ir.aboutamazon.com"]
reference_facts = ["CEO: Andy Jassy", "Headquarters: Seattle, Washington"]

[[company]]
name = "Snowflake"
ticker = "SNOW"
primary_domains = ["snowflake.com", "investors.snowflake.com"]
reference_facts = ["CEO: Sridhar Ramaswamy"]

[[company]]
name = "Cisco"
ticker = "CSCO"
primary_domains = ["cisco.com", "newsroom.cisco.com", "investor.cisco.com"]
reference_facts = ["CEO: Chuck Robbins", "Headquarters: San Jose, California"]

[[company]]
name = "Databricks"            # private: no ticker
primary_domains = ["databricks.com"]
reference_facts = ["CEO: Ali Ghodsi", "Headquarters: San Francisco, California"]
```
`sec.gov` counts as a primary source for every public company. **Reference facts come from my training data and must be verified by you before they're relied on.**

## Proposed scoring criteria (to iterate on)

### A. Deterministic checks (code, no LLM)
| ID | Check | Metric | Pass bar (draft) |
|---|---|---|---|
| D1 | Structure | All 5 sections + Sales/Technical subsections present | all present |
| D2 | Citation coverage | Share of bullets/persona rows ending with a link or `(No citation)` | 100% |
| D3 | Citation provenance | Unverified URLs (cited but never returned by Tavily) | 0 |
| D4 | News window | News items dated ≥ today − 90 days | 100% |
| D5 | Search budget | Tavily calls ≤ 10; credits (advanced = 2, basic = 1) | reported; cap respected |
| D6 | Query hygiene | News query has the ticker if public, none if private; no time words ("latest", "recent", years) | all queries clean |
| D7 | Primary-source share | Share of cited URLs on `primary_domains` or sec.gov (per section) | reported (no bar yet) |
| D8 | No-citation rate | `(No citation)` share per section; factual sections should be low | Overview/News/Strategy/Personas ≤ 10% |

### B. LLM judge: source correctness (per claim, with the cited result's Tavily content) — issues #4/#5
| ID | Question to judge | Labels | Metric |
|---|---|---|---|
| J1 | **Support:** is the claim supported by the cited source's text? | supported / partial / unsupported / insufficient-text | % supported (+partial) |
| J2 | **Subject:** is the account the main subject of the cited source? | main / mentioned / unrelated | % main (news + overview) |
| J3 | **Event date (news only):** does the date in the brief match the event date in the source text? | event-date / publication-date / wrong / not-stated | % event-date |
| J4 | **Source quality:** what kind of source is it? | primary / reputable-secondary / aggregator-or-low | % primary + reputable |

### C. LLM judge: section quality (per brief, 1–5 with a one-line rationale)
| ID | Criterion |
|---|---|
| Q1 | Reference facts: does the brief match `reference_facts` (also flags contradictions)? |
| Q2 | Overview completeness: business, industry, size, HQ, products |
| Q3 | Personas relevance: real, current, decision-relevant roles, both business and technical |
| Q4 | Talking points grounding: every point traces to facts in the brief, with no invented facts |
| Q5 | Usefulness: is it actionable for Sales and for Technical Presales separately? |

### Aggregation
- Per company: D-check pass/fail, J-label percentages, Q scores.
- Overall: the mean of each metric across companies.
- A company **passes** if D1–D4 pass, J1 ≥ 90%, J2 ≥ 80% for news, and the mean of Q1–Q5 ≥ 4. The bars are drafts to tune after the first run.

### Judge call pattern
One judge call per brief section (about 5 calls per company). Each call gets the section's claims, the cited URLs, and the Tavily `content` for those URLs from the record. The judge returns structured labels per claim. One more call scores Q1–Q5.

## Cost and time (estimate per full run of 5 companies)
- **Agent:** about 5 × (4–7 Tavily calls, 30–60 s).
- **Judge:** about 6 Bedrock calls per company, roughly 15–30k input tokens each.
- **Tavily:** about 20–35 credits per eval run, roughly $0.16–$0.28 at pay-as-you-go.
- Companies run one at a time by default; `--concurrency N` is optional.

## Steps / commits
1. `feat: add --record JSON output to starter_agent` + tests (record content from a fake stream).
2. `feat: add eval golden set config and deterministic scoring` (`golden_set.toml`, `scoring.py`) + tests on fixture records.
3. `feat: add LLM judge for source correctness and section quality` (`judge.py`) + tests with a fake structured LLM.
4. `feat: add eval runner and local report` (`run_evals.py`, `report.md`/`scores.csv`, `.gitignore` for results) + tests.
5. `docs:` README eval section + CLAUDE.md commands (summary to you first).
6. Open issue: "Integrate brief evals with LangSmith tracing (datasets, experiments, feedback)". Link #4, #5.
7. Push and open the PR.

## Verification
- Unit tests: `uv run --with pytest --with-requirements starter_agent.py pytest -q`; ruff clean on new files.
- End to end: `uv run evals/run_evals.py --companies Databricks` (one private company, cheap), then the full set. Inspect `report.md`. Spot-check 5 judge labels by hand against the record's Tavily content.
