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
"""
Minimal Tavily + LangChain agent CLI.

Setup:
  1. Create a Tavily API key: https://app.tavily.com
  2. Export both keys or add them to a .env file:
       TAVILY_API_KEY="tvly-..."
  3. Run:
       uv run starter_agent.py "What are the latest trends in agent evaluation?"

This is intentionally simple and uses streaming to improve user experience. It creates a LangChain agent with a Nebius-hosted
chat model and the Tavily search tool, then streams the agent run in the console.

You are not required to follow the below sample code. 

"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_aws import ChatBedrockConverse
from langchain_tavily import TavilySearch
from rich.console import Console
from rich.panel import Panel
from rich.text import Text


load_dotenv()

app = typer.Typer(add_completion=False)
console = Console()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a concise research assistant.
Use Tavily search when you need current or factual web information.
Answer the user's question directly and include source URLs when available.
"""

BRIEF_NEWS_WINDOW_DAYS = 90
BRIEF_MAX_SEARCHES = 10
URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")

BRIEF_PROMPT = """You are an account research assistant for a Sales Representative and a
Technical Presales engineer preparing for a meeting with the account named by the user.
Today is {today}.

Research process. Use Tavily search for every section except Suggested talking points:
1. In your first step, run these four Tavily searches together:
   - Overview: the account's business, industry, size, headquarters and key products.
   - Recent news: topic="news", start_date="{since}". Query with the account's name plus its
     stock ticker when it is publicly traded; omit the ticker otherwise.
   Keep every query to the account name and topic keywords. Never add time words such as
   "latest" or "recent", or a year; start_date already sets the time window.
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
Name executives when public. Use a Markdown table with columns
Name | Title | Relevance | Source, where every row's Source is its own [title](URL) link
or "(No citation)".

## Suggested talking points
Derived from the sections above; no new search.
### Sales
Business value, outcomes and timing hooks.
### Technical
Architecture, integration, security and technical-fit angles.

Citation rules (mandatory):
- Write every statement as a bullet (or, in Main personas, a table row) that ends with its
  source as a Markdown link: [title](URL).
- Use only URLs returned by Tavily search. Never invent or guess URLs.
- If a statement is not backed by a search result (for example a suggested talking point
  or your own inference), end it with "(No citation)".
- Do not add a sources list; one is generated automatically from the search results.
"""

llm = ChatBedrockConverse(
    model_id="us.anthropic.claude-sonnet-4-6",
    region_name="us-west-2",
    max_tokens=64000,
    credentials_profile_name="amirasf+genai",
    additional_model_request_fields={
        "thinking": {"type": "adaptive"},
    },
)


def require_env(name: str, instructions: str) -> None:
    if os.getenv(name):
        return
    console.print(f"[bold red]Missing {name}[/bold red]")
    console.print(instructions)
    raise typer.Exit(code=1)


def brief_prompt(today: date) -> str:
    since = today - timedelta(days=BRIEF_NEWS_WINDOW_DAYS)
    return BRIEF_PROMPT.format(
        today=today.isoformat(),
        since=since.isoformat(),
        max_searches=BRIEF_MAX_SEARCHES,
    )


def search_results(content: Any) -> list[dict[str, Any]]:
    """Tavily results from a tool message; empty for non-search content such as the limit message."""
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return [r for r in payload.get("results", []) if isinstance(r, dict)]


def collect_sources(content: Any, sources: dict[str, str]) -> None:
    """Record every URL Tavily actually returned; citations are verified against these."""
    for result in search_results(content):
        if result.get("url"):
            sources.setdefault(result["url"], result.get("title") or "Untitled")


def write_record(path: Path, record: dict[str, Any]) -> None:
    """Persist a run for offline evaluation, so scoring never needs to re-run the agent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_url(url: str) -> str:
    return url.rstrip(".,;:").rstrip("/")


def build_source_appendix(answer: str, sources: dict[str, str]) -> str:
    """Split URLs into cited-and-verified, retrieved-but-uncited, and cited-but-never-retrieved."""
    known = {normalize_url(url): (url, title) for url, title in sources.items()}
    cited = list(
        dict.fromkeys(normalize_url(url) for url in URL_PATTERN.findall(answer))
    )
    verified = [known[url] for url in cited if url in known]
    unverified = [url for url in cited if url not in known]
    additional = [entry for key, entry in known.items() if key not in cited]

    def section(title: str, items: list[str]) -> list[str]:
        return [f"## {title}", *(items or ["- None"]), ""]

    return "\n".join(
        section(
            "Sources (cited, returned by Tavily)",
            [f"- [{t}]({u})" for u, t in verified],
        )
        + section(
            "Additional research (returned by Tavily, not cited)",
            [f"- [{t}]({u})" for u, t in additional],
        )
        + section(
            "Unverified citations (not returned by Tavily)",
            [f"- {u}" for u in unverified],
        )
    ).strip()


def message_text(message: Any) -> str:
    """Extract streamed text from a LangChain message or message chunk."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def flush() -> None:
    console.file.flush()


def truncate(value: Any, limit: int = 900) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def print_tool_call(name: str, args: Any) -> None:
    console.print()
    console.print(
        Panel(
            Text(truncate(args, limit=700)),
            title=f"Tool call: {name}",
            border_style="yellow",
        )
    )


def format_tool_result(content: Any) -> str:
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return truncate(content)

    if not isinstance(payload, dict) or "results" not in payload:
        return truncate(payload)

    lines = [f"Query: {payload.get('query', '')}", ""]
    for index, result in enumerate(payload.get("results", [])[:5], start=1):
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        snippet = " ".join(result.get("content", "").split())
        lines.append(f"{index}. {title}")
        lines.append(f"   {url}")
        if snippet:
            lines.append(f"   {truncate(snippet, limit=220)}")
        lines.append("")
    return "\n".join(lines).strip()


def print_tool_result(message: Any) -> None:
    name = getattr(message, "name", None) or "tool"
    content = format_tool_result(getattr(message, "content", ""))
    console.print()
    console.print(
        Panel(
            Text(content),
            title=f"Tool result: {name}",
            border_style="yellow",
        )
    )


@app.command()
def main(
    question: Annotated[
        list[str], typer.Argument(help="Question, or account name with --brief")
    ],
    brief: Annotated[
        bool,
        typer.Option(
            "--brief", help="Research the account and print a sales/presales brief."
        ),
    ] = False,
    tracing: Annotated[
        bool,
        typer.Option(
            "--tracing/--no-tracing",
            help="LangSmith tracing (needs LANGSMITH_API_KEY).",
        ),
    ] = True,
    record: Annotated[
        Path | None,
        typer.Option(
            "--record", help="Write the answer, searches and sources to this JSON file."
        ),
    ] = None,
) -> None:
    """Ask a question and stream a small LangChain agent that searches with Tavily."""

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    # LangChain reads LANGSMITH_TRACING from the environment; the CLI flag decides its value.
    tracing_enabled = tracing and bool(os.getenv("LANGSMITH_API_KEY"))
    os.environ["LANGSMITH_TRACING"] = "true" if tracing_enabled else "false"
    if tracing_enabled:
        logger.info(
            "LangSmith tracing enabled (project: %s)",
            os.getenv("LANGSMITH_PROJECT", "default"),
        )
    elif tracing:
        logger.info(
            "LangSmith tracing disabled (set LANGSMITH_API_KEY in .env to enable)"
        )
    else:
        logger.info("LangSmith tracing disabled (--no-tracing)")

    require_env(
        "TAVILY_API_KEY",
        "Create one at https://app.tavily.com, then run: export TAVILY_API_KEY='tvly-...'",
    )

    question_text = " ".join(question)
    system_prompt = brief_prompt(date.today()) if brief else SYSTEM_PROMPT
    user_message = f"Account: {question_text}" if brief else question_text

    search_tool = TavilySearch()
    middleware = (
        [
            ToolCallLimitMiddleware(
                tool_name=search_tool.name, run_limit=BRIEF_MAX_SEARCHES
            )
        ]
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
    console.rule("[bold blue]Agent stream")

    tool_buffers: dict[str, dict[str, str]] = {}
    printed_tool_calls: set[str] = set()
    assistant_started = False
    last_event_was_text = False
    sources: dict[str, str] = {}
    answer_parts: list[str] = []
    searches: dict[str, dict[str, Any]] = {}
    started = time.monotonic()

    try:
        stream = agent.stream(
            {"messages": [{"role": "user", "content": user_message}]},
            stream_mode=["messages", "updates"],
        )

        for mode, data in stream:
            if mode == "messages":
                message, _metadata = data

                if getattr(message, "type", None) == "tool":
                    continue

                tool_call_chunks = getattr(message, "tool_call_chunks", []) or []
                if tool_call_chunks:
                    if last_event_was_text:
                        console.print()
                        last_event_was_text = False

                    for chunk in tool_call_chunks:
                        key = str(chunk.get("id") or chunk.get("index") or "tool_call")
                        buffer = tool_buffers.setdefault(key, {"name": "", "args": ""})

                        if chunk.get("name"):
                            buffer["name"] += chunk["name"]
                        if chunk.get("args"):
                            buffer["args"] += chunk["args"]

                        if key not in printed_tool_calls and buffer["name"]:
                            printed_tool_calls.add(key)
                            console.print(
                                f"\n[bold yellow]Tool call[/bold yellow] [yellow]{buffer['name']}[/yellow]",
                                highlight=False,
                            )
                            console.print("[dim yellow]args: [/dim yellow]", end="")

                        if chunk.get("args"):
                            console.print(
                                chunk["args"], style="yellow", end="", highlight=False
                            )
                            flush()
                    continue

                text = message_text(message)
                if text:
                    answer_parts.append(text)
                    if not assistant_started:
                        if printed_tool_calls:
                            console.print()
                        console.print("\n[bold green]Assistant[/bold green]")
                        assistant_started = True
                    console.print(text, end="", highlight=False, markup=False)
                    flush()
                    last_event_was_text = True

            elif mode == "updates":
                for node_update in data.values():
                    if not isinstance(node_update, dict):
                        continue  # middleware hooks report None when they change nothing
                    for message in node_update.get("messages", []):
                        if getattr(message, "type", None) == "ai":
                            for tool_call in getattr(message, "tool_calls", []) or []:
                                searches.setdefault(
                                    str(tool_call.get("id")),
                                    {"args": tool_call.get("args", {}), "results": []},
                                )
                                key = str(
                                    tool_call.get("id")
                                    or tool_call.get("name")
                                    or "tool_call"
                                )
                                if key not in printed_tool_calls:
                                    printed_tool_calls.add(key)
                                    print_tool_call(
                                        tool_call.get("name", "tool"),
                                        tool_call.get("args", {}),
                                    )

                        if getattr(message, "type", None) == "tool":
                            if last_event_was_text:
                                console.print()
                                last_event_was_text = False
                            print_tool_result(message)
                            content = getattr(message, "content", "")
                            collect_sources(content, sources)
                            searches.setdefault(
                                str(getattr(message, "tool_call_id", "")),
                                {"args": {}, "results": []},
                            )["results"] = search_results(content)

        if last_event_was_text:
            console.print()

        if brief:
            console.rule("[bold magenta]Sources (from Tavily tool output)")
            console.print(
                build_source_appendix("".join(answer_parts), sources),
                markup=False,
                highlight=False,
                soft_wrap=True,  # keep long URLs on one line so they stay copyable
            )

        if record:
            write_record(
                record,
                {
                    "input": question_text,
                    "brief": brief,
                    "date": date.today().isoformat(),
                    "answer": "".join(answer_parts),
                    "searches": list(searches.values()),
                    "sources": sources,
                    "duration_s": round(time.monotonic() - started, 1),
                },
            )

    except KeyboardInterrupt:
        console.print("\n[red]Interrupted.[/red]")
        raise typer.Exit(code=130) from None
    except Exception as exc:
        console.print(f"\n[bold red]Agent run failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from None


if __name__ == "__main__":
    app()
