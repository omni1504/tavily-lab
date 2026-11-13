"""Tests for parse_session.py.  Run: python -m unittest -v  (from parser/)"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from parse_session import demote_headings, local_time, read_records, render

SAMPLE = Path(__file__).parent / "samples" / "session.jsonl"


def md_from(records: list[dict[str, Any]], **kw: Any) -> str:
    opts: dict[str, Any] = {"tools": True, "max_result": 800, "thinking": False} | kw
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "session.jsonl"
        # Trailing malformed line mimics a log that is still being written.
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n{broken json\n")
        return render(read_records(path), **opts)


def user(text: str, uid: str = "u1") -> dict[str, Any]:
    return {
        "type": "user",
        "uuid": uid,
        "sessionId": "s",
        "timestamp": "2026-11-13T00:00:00Z",
        "message": {"role": "user", "content": text},
    }


def assistant(blocks: list[dict[str, Any]], uid: str = "a1") -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": uid,
        "sessionId": "s",
        "timestamp": "2026-11-13T00:00:01Z",
        "message": {"role": "assistant", "content": blocks},
    }


def tool_result(text: str, is_error: bool = False, uid: str = "r1") -> dict[str, Any]:
    return {
        "type": "user",
        "uuid": uid,
        "sessionId": "s",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": text,
                    "is_error": is_error,
                }
            ],
        },
    }


class RenderTests(unittest.TestCase):
    def test_strips_ide_tags_and_keeps_prompt(self) -> None:
        md = md_from(
            [user("<ide_opened_file>opened x.py</ide_opened_file>\nHello agent")]
        )
        self.assertIn("Hello agent", md)
        self.assertNotIn("ide_opened_file", md)

    def test_drops_noise_records(self) -> None:
        md = md_from(
            [
                {"type": "api-request", "sessionId": "s", "message": "SECRET-PAYLOAD"},
                {
                    "type": "attachment",
                    "sessionId": "s",
                    "attachment": {"type": "output_style", "x": "NOISE"},
                },
                user("hi"),
            ]
        )
        self.assertNotIn("SECRET-PAYLOAD", md)
        self.assertNotIn("NOISE", md)

    def test_queued_mid_turn_message(self) -> None:
        rec = {
            "type": "attachment",
            "uuid": "q",
            "sessionId": "s",
            "attachment": {
                "type": "queued_command",
                "prompt": [{"type": "text", "text": "also do Y"}],
            },
        }
        self.assertIn("User (sent mid-turn)", md_from([rec]))

    def test_interrupt_marker(self) -> None:
        self.assertIn("⏹", md_from([user("[Request interrupted by user]")]))

    def test_tool_call_and_error_result(self) -> None:
        md = md_from(
            [
                assistant(
                    [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": "ls", "description": "List files"},
                        }
                    ]
                ),
                tool_result("denied", is_error=True),
            ]
        )
        self.assertIn("**Bash**: `List files — ls`", md)
        self.assertIn("error / rejected", md)

    def test_no_tools_and_truncation(self) -> None:
        recs = [
            assistant(
                [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "/a"},
                    }
                ]
            ),
            tool_result("x" * 2000),
        ]
        self.assertNotIn("Read", md_from(recs, tools=False))
        self.assertIn("more chars", md_from(recs, max_result=100))

    def test_dedupes_by_uuid(self) -> None:
        self.assertEqual(
            md_from([user("once", "same"), user("once", "same")]).count("once"), 1
        )

    def test_local_time_parses_utc_z_suffix(self) -> None:
        self.assertRegex(
            local_time({"timestamp": "2026-11-13T00:00:00.123Z"}), r"^2026-11-1[23] "
        )
        self.assertEqual(local_time({"timestamp": "garbage"}), "")

    def test_demote_headings_skips_code_fences(self) -> None:
        self.assertEqual(
            demote_headings("## H\n```\n# comment\n```"), "#### H\n```\n# comment\n```"
        )


@unittest.skipUnless(SAMPLE.exists(), "copy a session log to samples/session.jsonl")
class SampleSessionTests(unittest.TestCase):
    def test_real_session(self) -> None:
        md = render(read_records(SAMPLE), tools=True, max_result=800, thinking=False)
        self.assertGreater(md.count("## User"), 0)
        self.assertGreater(md.count("## Assistant"), 0)
        prose = "".join(md.split("```")[0::2])  # text outside code fences
        for noise in (
            "api-request",
            "file-history-snapshot",
            "<system-reminder>",
            "<ide_opened_file>",
        ):
            self.assertNotIn(noise, prose)


if __name__ == "__main__":
    unittest.main()
