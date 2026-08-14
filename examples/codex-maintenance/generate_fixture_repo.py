"""Create a tiny offline maintenance fixture in an explicitly chosen directory."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


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
    _git(root, "init")
    _git(root, "config", "user.email", "issue-proof@example.invalid")
    _git(root, "config", "user.name", "IssueProof Fixture")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "offline fixture")
    _git(root, "remote", "add", "origin", "https://github.com/example/offline-fixture.git")
    print(f"fixture: {root}")
    print(
        "baseline: issue-proof collect --issue-file .\\issue.md --command-argv "
        ".\\baseline-command.json --output .\\baseline-1 --repo-root . --identity-mode github"
    )
    print("repeat the baseline command for .\\baseline-2")
    print("simulated fix: New-Item -ItemType File -Path .\\fixed.marker -Force")
    print(
        "verification: issue-proof verify --baseline .\\baseline-1\\report.json "
        "--command-argv .\\verify-command.json --output .\\verified --repo-root . "
        "--identity-mode github"
    )
    print(
        "receipt: issue-proof receipt --baseline .\\baseline-1\\report.json "
        "--baseline .\\baseline-2\\report.json --verification .\\verified\\report.json "
        "--output .\\receipt --repo-root . --identity-mode github"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
