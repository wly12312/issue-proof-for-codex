"""Stable Skill entry point that delegates to the installed project CLI."""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
source_root = project_root / "src"
if str(source_root) not in sys.path:
    sys.path.insert(0, str(source_root))

from issue_proof.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
