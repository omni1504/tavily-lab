"""Make the single-file app at the repo root importable from tests (there is no package)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
