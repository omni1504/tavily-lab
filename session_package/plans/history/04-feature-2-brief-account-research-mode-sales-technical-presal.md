# Feature 2 — `--brief` account research mode (Sales + Technical Presales)

## Context
The script is a general Q&A research agent. The new `--brief` mode turns it into an account-research tool for a Sales Rep and a Technical Presales engineer preparing for a customer meeting.
- **Input:** an account name only.
- **Output:** one combined Markdown brief, streamed to the console, with these sections: Overview, Recent news (last 90 days), Strategic priorities, Main personas, Suggested talking points (Sales and Technical sub-bullets).
- **Citations:** every statement carries an inline citation with its URL, or a "(No citation)" label.

Decisions agreed:
- **Searches:** 4 research searches run in one batch, with refined follow-up searches for thin sections. A hard cap of 10 Tavily calls per run is enforced in code.
- **Citations:** the model cites inline, and code builds a sources appendix from the actual Tavily tool output. Inline citations are checked against it.

Without `--brief`, behaviour is unchanged: same prompt, no search cap, no appendix.

Branch: `feat/account-brief`. All code changes are in `starter_agent.py`. No new dependencies: `ToolCallLimitMiddleware` ships with the installed `langchain` 1.5.0, and `re` and `datetime` are standard library.

## Exact code changes — `starter_agent.py`

**1. Imports**
```python
import re
from datetime import date, timedelta
...
from langchain.agents.middleware import ToolCallLimitMiddleware
```

**2. Constants** (after `SYSTEM_PROMPT`):
```python
BRIEF_NEWS_WINDOW_DAYS = 90
BRIEF_MAX_SEARCHES = 10
URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")

BRIEF_PROMPT = """You are an account research assistant for a Sales Representative and a
Technical Presales engineer preparing for a meeting with the account named by the user.
Today is {today}.

Research process. Use Tavily search for every section except Suggested talking points:
1. In your first step, run these four Tavily searches together:
   - Overview: the account's business, industry, size, headquarters and key products.
   - Recent news: topic="news", start_date="{since}".
   - Strategic priorities: strategy, initiatives, investments, earnings commentary.
   - Main personas: leadership team and technology/business decision-makers.
2. If a section has fewer than 2 relevant results, run a refined Tavily search for that
   section, at most 2 more times per section. Never exceed {max_searches} searches in total.
3. If a section is still thin, write "Insufficient public data (No citation)".

Write a Markdown brief with exactly these sections, in this order:

## Overview
From Tavily search: what the company does, industry, size, headquarters, key products.

## Recent news (since {since})
From Tavily news search: only items published on or after {since}, each starting with its date.

## Strategic priorities
From Tavily search: stated goals, initiatives and investments.

## Main personas
From Tavily search: roles likely involved in a buying decision, business and technical.
Name executives when public.

## Suggested talking points
Derived from the sections above; no new search.
### Sales
Business value, outcomes and timing hooks.
### Technical
Architecture, integration, security and technical-fit angles.

Citation rules (mandatory):
- Write every statement as a bullet that ends with its source as a Markdown link: [title](URL).
- Use only URLs returned by Tavily search. Never invent or guess URLs.
- If a statement is not backed by a search result (for example a suggested talking point
  or your own inference), end it with "(No citation)".
- Do not add a sources list; one is generated automatically from the search results.
"""
```

**3. Helpers** (after `require_env`). They hold the date maths and the deterministic citation logic, so both can be tested.
```python
def brief_prompt(today: date) -> str:
    since = today - timedelta(days=BRIEF_NEWS_WINDOW_DAYS)
    return BRIEF_PROMPT.format(
        today=today.isoformat(), since=since.isoformat(), max_searches=BRIEF_MAX_SEARCHES
    )


def collect_sources(content: Any, sources: dict[str, str]) -> None:
    """Record every URL Tavily actually returned; citations are verified against these."""
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return  # e.g. the tool-call-limit message: not a search result, nothing to record
    if not isinstance(payload, dict):
        return
    for result in payload.get("results", []):
        if isinstance(result, dict) and result.get("url"):
            sources.setdefault(result["url"], result.get("title") or "Untitled")


def normalize_url(url: str) -> str:
    return url.rstrip(".,;:").rstrip("/")


def build_source_appendix(answer: str, sources: dict[str, str]) -> str:
    """Split URLs into cited-and-verified, retrieved-but-uncited, and cited-but-never-retrieved."""
    known = {normalize_url(url): (url, title) for url, title in sources.items()}
    cited = list(dict.fromkeys(normalize_url(url) for url in URL_PATTERN.findall(answer)))
    verified = [known[url] for url in cited if url in known]
    unverified = [url for url in cited if url not in known]
    additional = [entry for key, entry in known.items() if key not in set(cited)]

    def section(title: str, items: list[str]) -> list[str]:
        return [f"## {title}", *(items or ["- None"]), ""]

    return "\n".join(
        section("Sources (cited, returned by Tavily)", [f"- [{t}]({u})" for u, t in verified])
        + section("Additional research (returned by Tavily, not cited)",
                  [f"- [{t}]({u})" for u, t in additional])
        + section("Unverified citations (not returned by Tavily)", [f"- {u}" for u in unverified])
    ).strip()
```

**4. `main` signature**
```python
def main(
    question: Annotated[
        list[str], typer.Argument(help="Question, or account name with --brief")
    ],
    brief: Annotated[
        bool,
        typer.Option("--brief", help="Research the account and print a sales/presales brief."),
    ] = False,
) -> None:
```

**5. Inside `main`**: prompt, message and search cap.
```python
    question_text = " ".join(question)
    system_prompt = brief_prompt(date.today()) if brief else SYSTEM_PROMPT
    user_message = f"Account: {question_text}" if brief else question_text

    search_tool = TavilySearch()
    middleware = (
        [ToolCallLimitMiddleware(tool_name=search_tool.name, run_limit=BRIEF_MAX_SEARCHES)]
        if brief
        else []
    )

    agent = create_agent(
        model=llm,
        tools=[search_tool],
        system_prompt=system_prompt,
        middleware=middleware,
    )

    title = "Account brief" if brief else "Question"
    console.print(Panel.fit(question_text, title=title, border_style="cyan"))
```

**6. Stream loop**: 3 small additions. Nothing else changes.
```python
    sources: dict[str, str] = {}
    answer_parts: list[str] = []
    ...
            {"messages": [{"role": "user", "content": user_message}]},
    ...
                text = message_text(message)
                if text:
                    answer_parts.append(text)          # new
    ...
                        if getattr(message, "type", None) == "tool":
                            ...
                            print_tool_result(message)
                            collect_sources(getattr(message, "content", ""), sources)  # new
    ...
        if last_event_was_text:
            console.print()

        if brief:                                      # new
            console.rule("[bold magenta]Sources (from Tavily tool output)")
            console.print(build_source_appendix("".join(answer_parts), sources),
                          markup=False, highlight=False)
```

## Tests — `tests/test_brief.py` (new)
LangSmith, Bedrock and Tavily are never called. The fake agent streams real `langchain_core` `ToolMessage` / `AIMessageChunk` objects, and `TavilySearch` is replaced with a stub that has `name="tavily_search"`.
1. **`brief_prompt(date(2026, 11, 13))`** contains:
   - `Today is 2026-11-13` and `start_date="2026-08-15"`;
   - `Never exceed 10 searches`;
   - all five `##` headings;
   - `(No citation)`.
2. **`collect_sources`**:
   - parses both a JSON string and a dict;
   - ignores non-JSON content (the limit message), results without a URL, and non-dict payloads;
   - drops duplicate URLs.
3. **`build_source_appendix`**:
   - a cited URL that Tavily returned is listed as verified, including trailing `/` and `.` variants;
   - a cited URL that Tavily never returned is listed as unverified;
   - a returned but uncited URL goes under Additional research;
   - empty groups show `- None`.
4. **CLI `--brief Snowflake`**:
   - `create_agent` receives the brief prompt and a `ToolCallLimitMiddleware` (`tavily_search`, run limit 10);
   - the message is `Account: Snowflake`;
   - the output has the `Account brief` panel and all three appendix groups, with the expected URLs in each.
5. **Regression without `--brief`**: `SYSTEM_PROMPT`, `middleware=[]`, the raw question, and no appendix printed.

## Commits
1. `feat: add --brief account research mode with capped Tavily searches`: prompt, flag, middleware + tests 1, 4 (prompt/middleware parts), 5.
2. `feat: verify brief citations against Tavily tool output`: `collect_sources`, `build_source_appendix`, stream-loop hooks + tests 2, 3, 4 (appendix parts).
3. `docs: document --brief mode`: README Run section gets a `--brief` example and notes on the sections, citations and appendix. A short summary goes to you before the README is written.
4. Push and open the PR with check output.

## Verification
- `uv run --with pytest --with-requirements starter_agent.py pytest -q` → all pass.
- `uvx ruff check tests` and `uvx ruff format --check tests` → clean. No new ruff findings in `starter_agent.py`.
- Manual: `uv run starter_agent.py --brief "Snowflake"`. Check:
  - the first step shows 4 batched `tavily_search` calls, including `topic: news` with `start_date` = today − 90 days;
  - there are 10 or fewer searches in total;
  - all 5 sections appear, and every bullet ends with a link or `(No citation)`;
  - news dates fall in the window;
  - the appendix lists verified, additional and unverified URLs;
  - the trace appears in LangSmith `tavily-research-agent`.
- Risk: `max_tokens=4096` (shared with adaptive thinking) may truncate a long brief. If it does, I'll stop and ask before changing it.
- Manual regression: `uv run starter_agent.py "What is Tavily?"` is unchanged.
