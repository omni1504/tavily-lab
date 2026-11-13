#!/usr/bin/env python3
"""Convert a Claude Code session log (JSONL) into a readable Markdown transcript.

Keeps only what matters for reading a conversation:
  - user prompts (IDE/system wrapper tags stripped) and mid-turn queued messages
  - assistant text
  - tool calls (one-line summary) and their results (truncated)
Drops API request/telemetry records, attachments, file-history snapshots, etc.

Usage:
  python parse_session.py SESSION.jsonl                 # print Markdown to stdout
  python parse_session.py SESSION.jsonl -o chat.md      # write to file
  python parse_session.py SESSION.jsonl --no-tools      # conversation only
  python parse_session.py SESSION.jsonl --max-result 0  # hide tool output bodies
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

# Wrapper tags injected by the IDE / harness around user text.
NOISE_TAGS = re.compile(
    r"<(ide_opened_file|ide_selection|system-reminder|command-[a-z-]+|local-command-[a-z-]+)>"
    r".*?</\1>",
    re.DOTALL,
)
INTERRUPT = re.compile(r"^\[Request interrupted by user[^\]]*\]$")

# Most informative argument per tool, used for the one-line call summary.
KEY_ARGS = {
    "Bash": ("description", "command"),
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "WebFetch": ("url",),
    "ToolSearch": ("query",),
    "EnterWorktree": ("name", "path"),
    "Agent": ("description",),
    "Skill": ("skill",),
}


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a partially-written last line
            uid = rec.get("uuid")
            if uid and uid in seen:
                continue
            if uid:
                seen.add(uid)
            yield rec


def clean_user_text(text: str) -> str:
    return NOISE_TAGS.sub("", text).strip()


def text_blocks(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
    return []


def truncate(text: str, limit: int) -> str:
    text = text.rstrip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n… [{len(text) - limit} more chars]"


def summarize_call(name: str, args: dict[str, Any]) -> str:
    keys = KEY_ARGS.get(name)
    if name == "AskUserQuestion":
        return "; ".join(q.get("question", "") for q in args.get("questions", []))
    if keys:
        parts = [str(args[k]) for k in keys if args.get(k)]
        if parts:
            return " — ".join(
                p.splitlines()[0] if i == 0 else p for i, p in enumerate(parts)
            )
    return truncate(json.dumps(args, ensure_ascii=False), 200)


def result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, list):
        parts = []
        for b in content:
            if b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif b.get("type") == "tool_reference":
                parts.append(f"(loaded tool: {b.get('tool_name', '?')})")
        return "\n".join(parts)
    return str(content or "")


def fence(text: str, lang: str = "") -> str:
    ticks = "````" if "```" in text else "```"
    return f"{ticks}{lang}\n{text}\n{ticks}"


def local_time(rec: dict[str, Any]) -> str:
    """UTC ISO timestamp -> local 'YYYY-MM-DD HH:MM:SS'."""
    ts = rec.get("timestamp")
    if not ts:
        return ""
    try:
        # Parse the fixed-width prefix: fromisoformat() rejects a trailing "Z" before 3.11.
        utc = datetime.strptime(ts[:19] + "+0000", "%Y-%m-%dT%H:%M:%S%z")
        return utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


def demote_headings(text: str, by: int = 2) -> str:
    """Push Markdown headings in assistant text below the transcript's own '## Turn' level."""
    lines, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and (m := re.match(r"^(#{1,6}) ", line)):
            line = "#" * min(len(m[1]) + by, 6) + line[len(m[1]) :]
        lines.append(line)
    return "\n".join(lines)


def inline_code(text: str) -> str:
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def render(
    records: Iterator[dict[str, Any]], *, tools: bool, max_result: int, thinking: bool
) -> str:
    out: list[str] = []
    title = None
    session = None

    def heading(who: str, rec: dict[str, Any]) -> None:
        stamp = local_time(rec)
        out.append(f"\n## {who}" + (f"  ·  {stamp}" if stamp else "") + "\n")

    last_role = None
    for rec in records:
        rtype = rec.get("type")
        session = session or rec.get("sessionId")

        if rtype == "ai-title":
            title = rec.get("aiTitle") or title
            continue

        if rtype == "attachment":
            att = rec.get("attachment") or {}
            if att.get("type") != "queued_command":
                continue
            prompt = att.get("prompt")
            text = clean_user_text("\n".join(text_blocks(prompt)))
            if text:
                heading("User (sent mid-turn)", rec)
                out.append(text)
                last_role = "user"
            continue

        if rtype == "user":
            content = rec.get("message", {}).get("content")
            # Tool results
            if isinstance(content, list) and any(
                b.get("type") == "tool_result" for b in content
            ):
                if not tools:
                    continue
                for b in content:
                    if b.get("type") != "tool_result" or max_result <= 0:
                        continue
                    body = truncate(result_text(b), max_result)
                    label = (
                        "<b>✗ error / rejected</b>" if b.get("is_error") else "result"
                    )
                    if body.strip():
                        out.append(
                            f"<details><summary>{label}</summary>\n\n{fence(body)}\n\n</details>\n"
                        )
                    elif b.get("is_error"):
                        out.append(f"{label}\n")
                continue
            # Human text
            text = clean_user_text("\n\n".join(text_blocks(content)))
            if not text:
                continue
            if INTERRUPT.match(text):
                out.append(f"\n> ⏹ _{text.strip('[]')}_\n")
                continue
            heading("User", rec)
            out.append(text)
            last_role = "user"
            continue

        if rtype == "assistant":
            for b in rec.get("message", {}).get("content", []) or []:
                btype = b.get("type")
                if btype == "text" and b.get("text", "").strip():
                    if last_role != "assistant":
                        heading("Assistant", rec)
                    out.append(demote_headings(b["text"].strip()) + "\n")
                    last_role = "assistant"
                elif btype == "thinking" and thinking and b.get("thinking", "").strip():
                    if last_role != "assistant":
                        heading("Assistant", rec)
                    out.append(
                        "> 💭 " + b["thinking"].strip().replace("\n", "\n> ") + "\n"
                    )
                    last_role = "assistant"
                elif btype == "tool_use" and tools:
                    if last_role != "assistant":
                        heading("Assistant", rec)
                    name = b.get("name", "tool")
                    call = truncate(
                        summarize_call(name, b.get("input") or {}), 300
                    ).replace("\n", " ")
                    out.append(f"🔧 **{name}**: {inline_code(call)}\n")
                    last_role = "assistant"
            continue
        # Everything else (api-request*, atis-latch, file-history, queue-operation, ...) is noise.

    header = (
        f"# {title or 'Claude Code session'}\n\n_Session `{session}`_\n"
        if session
        else "# Claude Code session\n"
    )
    return header + "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("session", type=Path, help="path to a session .jsonl file")
    ap.add_argument(
        "-o", "--output", type=Path, help="write Markdown here instead of stdout"
    )
    ap.add_argument(
        "--no-tools", action="store_true", help="hide tool calls and results"
    )
    ap.add_argument(
        "--max-result",
        type=int,
        default=800,
        help="max chars per tool result (0 = hide bodies)",
    )
    ap.add_argument(
        "--thinking", action="store_true", help="include thinking blocks when present"
    )
    args = ap.parse_args(argv)

    md = render(
        read_records(args.session),
        tools=not args.no_tools,
        max_result=args.max_result,
        thinking=args.thinking,
    )
    if args.output:
        args.output.write_text(md, encoding="utf-8")
        print(f"Wrote {args.output} ({len(md.splitlines())} lines)", file=sys.stderr)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
