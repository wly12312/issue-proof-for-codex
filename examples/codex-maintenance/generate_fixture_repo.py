"""Create a tiny offline maintenance fixture in an explicitly chosen directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "issue.md").write_text(
        "# Deterministic fixture bug\n\nThe command fails until fixed.marker exists.\n",
        encoding="utf-8",
    )
    (root / "src" / "bug_fixture.py").write_text(
        "import pathlib, sys\nsys.exit(0 if pathlib.Path('fixed.marker').exists() else 1)\n",
        encoding="utf-8",
    )
    (root / "baseline-command.json").write_text(
        json.dumps({"argv": ["python", "src/bug_fixture.py"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "verify-command.json").write_text(
        json.dumps({"argv": ["python", "src/bug_fixture.py"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"fixture: {root}")
    print("baseline: python src/bug_fixture.py  # exits 1 before the simulated fix")
    print("fix: create fixed.marker, then rerun the same argv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
