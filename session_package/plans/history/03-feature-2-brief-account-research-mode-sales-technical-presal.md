# Feature 2 — `--brief` account research mode (Sales + Technical Presales)

## Context
The script is a general Q&A research agent. The new `--brief` mode turns it into an account-research tool for a Sales Rep and a Technical Presales engineer preparing for a customer meeting.
- **Input:** an account name only.
- **Output:** one combined Markdown brief, streamed to the console, with these sections: Overview (from Tavily search), Recent news (last 90 days), Strategic priorities, Main personas, Suggested talking points (Sales and Technical sub-bullets).
- **Citations:** every statement carries a citation with its URL, or a "No citation" label.

Without `--brief`, behaviour is unchanged.

Branch: `feat/account-brief`. The only code changes are in `starter_agent.py`. No new dependencies, no new CLI options beyond `--brief`.

## Approach
Use a second system prompt plus today's date; no new tools and no post-processing.
- The installed `langchain-tavily` 0.2.18 already lets the model set `topic="news"` and `start_date`/`end_date` on each search call. The prompt therefore tells it to search news with `start_date` = today − 90 days.
- Today's date and the cutoff are computed in Python and injected into the prompt, because the model doesn't know the current date.
- The existing streaming/printing code (`message_text`, `print_tool_call`, `print_tool_result`, the stream loop) is reused as-is.

## Exact code changes — `starter_agent.py`

**1. Import**
```python
from datetime import date, timedelta
```

**2. Constants** (after `SYSTEM_PROMPT`):
```python
BRIEF_NEWS_WINDOW_DAYS = 90

BRIEF_PROMPT = """You are an account research assistant for a Sales Representative and a
Technical Presales engineer preparing for a meeting with the account named by the user.
Today is {today}. Research the account with Tavily search, then write a Markdown brief
with exactly these sections, in this order:

## Overview
What the company does, industry, size, headquarters, key products. Base it on Tavily search results.

## Recent news (since {since})
Only items published on or after {since}. Search with topic="news" and start_date="{since}".
Start each item with its publication date. If nothing qualifies, say so.

## Strategic priorities
Stated goals, initiatives and investments (e.g. from earnings, press releases, leadership statements).

## Main personas
Roles likely involved in a buying decision, both business and technical. Name executives when public.

## Suggested talking points
### Sales
Business value, outcomes and timing hooks tied to the findings above.
### Technical
Architecture, integration, security and technical-fit angles tied to the findings above.

Citation rules (mandatory):
- Write every statement as a bullet that ends with its source as a Markdown link: [title](URL).
- Use only URLs returned by Tavily search. Never invent or guess URLs.
- If a statement is not backed by a search result (for example your own inference or a
  suggested talking point), end it with "(No citation)" instead.
"""
```

**3. Single helper** (after `require_env`). It's kept because the date math needs a unit test:
```python
def brief_prompt(today: date) -> str:
    since = today - timedelta(days=BRIEF_NEWS_WINDOW_DAYS)
    return BRIEF_PROMPT.format(today=today.isoformat(), since=since.isoformat())
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

**5. Inside `main`**: choose the prompt and message. Only these lines change; the stream loop doesn't.
```python
    question_text = " ".join(question)
    system_prompt = brief_prompt(date.today()) if brief else SYSTEM_PROMPT
    user_message = f"Account: {question_text}" if brief else question_text

    search_tool = TavilySearch()

    agent = create_agent(
        model=llm,
        tools=[search_tool],
        system_prompt=system_prompt,
    )

    title = "Account brief" if brief else "Question"
    console.print(Panel.fit(question_text, title=title, border_style="cyan"))
    ...
        stream = agent.stream(
            {"messages": [{"role": "user", "content": user_message}]},
            stream_mode=["messages", "updates"],
        )
```

## Tests — `tests/test_brief.py` (new)
These use a fake agent and fake `TavilySearch`, so LangSmith, Bedrock and Tavily are never called. They're invoked with `CliRunner`, the same pattern as `tests/test_tracing.py`.
1. `brief_prompt(date(2026, 11, 13))` contains `Today is 2026-11-13`, `since 2026-08-15`, `start_date="2026-08-15"`, all five `##` section headings, and `(No citation)`.
2. `--brief Snowflake` → `create_agent` receives the brief prompt, the stream payload message is `Account: Snowflake`, and the output panel title is `Account brief`.
3. Regression without `--brief` → `create_agent` receives `SYSTEM_PROMPT` and the message is the raw question.

## Commits
1. `feat: add --brief account research mode`: items 1–5 + tests.
2. `docs: document --brief mode`: README Run section gets a `--brief` example and a section/citation summary. A short summary goes to you before the README is written.
3. Push and open the PR with check output.

## Verification
- `uv run --with pytest --with-requirements starter_agent.py pytest -q` → all pass. `uvx ruff check tests` and `uvx ruff format --check tests` → clean. No new ruff findings in `starter_agent.py`.
- Manual: `uv run starter_agent.py --brief "Snowflake"`. Check:
  - all 5 sections appear;
  - the tool-call panels show `topic: news` with `start_date` = today − 90 days;
  - every bullet ends with `[..](https://..)` or `(No citation)`;
  - news dates fall inside the window;
  - the trace appears in LangSmith `tavily-research-agent`.
- Risk: `max_tokens=4096` (shared with adaptive thinking) may truncate a long brief. If the manual run is cut off, I'll stop and ask before changing it.
- Manual regression: `uv run starter_agent.py "What is Tavily?"` still behaves as before.
