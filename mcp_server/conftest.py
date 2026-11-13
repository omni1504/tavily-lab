"""Make the repo root (starter_agent.py) and mcp_server/ importable from the MCP tests."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parent, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
