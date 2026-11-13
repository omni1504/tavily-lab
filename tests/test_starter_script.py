"""Regression: `starter_agent.py` once shipped with an unclosed `main(` signature."""

import ast
from pathlib import Path

STARTER = Path(__file__).resolve().parent.parent / "starter_agent.py"


def test_starter_script_is_valid_python() -> None:
    ast.parse(STARTER.read_text(encoding="utf-8"), filename=str(STARTER))
