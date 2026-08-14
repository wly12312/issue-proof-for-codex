"""Run the Phase 2 same-conversation CLI flow against a disposable offline fixture."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from issue_proof.cli import main
from issue_proof.codex.receipt import load_receipt


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _prepare_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    repo = root / "fixture"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "issue-proof@example.invalid")
    _git(repo, "config", "user.name", "IssueProof Offline")
    (repo / "README.md").write_text("offline fixture\n", encoding="utf-8")
    issue = repo / "issue.md"
    issue.write_text(
        "# Offline Phase 2 fixture\n\nThe command fails until fixed.marker exists.\n",
        encoding="utf-8",
    )
    argv_file = repo / "command-argv.json"
    argv_file.write_text(
        json.dumps(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,sys; sys.exit(1 if not pathlib.Path('fixed.marker').exists() "
                    "else 0)"
                ),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    check_argv_file = repo / "check-argv.json"
    check_argv_file.write_text(
        json.dumps(
            [
                sys.executable,
                "-c",
                ("import pathlib,sys; sys.exit(0 if pathlib.Path('fixed.marker').exists() else 1)"),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "README.md", "issue.md", "command-argv.json", "check-argv.json")
    _git(repo, "commit", "-m", "offline fixture")
    _git(repo, "remote", "add", "origin", "https://github.com/example/offline-fixture.git")
    return repo, issue, argv_file, check_argv_file


def _run(output_dir: Path, trace: Path | None) -> dict[str, object]:
    if output_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing offline output: {output_dir}")
    output_dir.mkdir(parents=True)
    repo, issue, argv_file, check_argv_file = _prepare_fixture(output_dir)
    baseline_paths = []
    for index in (1, 2):
        baseline_dir = output_dir / f"baseline-{index}"
        result = main(
            [
                "collect",
                "--issue-file",
                str(issue),
                "--command-argv",
                str(argv_file),
                "--repo-root",
                str(repo),
                "--identity-mode",
                "github",
                "--output",
                str(baseline_dir),
            ]
        )
        if result != 0:
            raise RuntimeError(f"baseline {index} returned {result}")
        baseline_paths.append(baseline_dir / "report.json")

    (repo / "fixed.marker").write_text("fixed\n", encoding="utf-8")
    verification_dir = output_dir / "verification"
    if (
        main(
            [
                "verify",
                "--baseline",
                str(baseline_paths[0]),
                "--command-argv",
                str(argv_file),
                "--repo-root",
                str(repo),
                "--identity-mode",
                "github",
                "--output",
                str(verification_dir),
            ]
        )
        != 0
    ):
        raise RuntimeError("verification returned a non-zero IssueProof status")

    check_dir = output_dir / "check"
    if (
        main(
            [
                "collect",
                "--issue-file",
                str(issue),
                "--command-argv",
                str(check_argv_file),
                "--repo-root",
                str(repo),
                "--identity-mode",
                "github",
                "--output",
                str(check_dir),
            ]
        )
        != 0
    ):
        raise RuntimeError("additional regression check returned a non-zero IssueProof status")

    receipt_dir = output_dir / "receipt"
    receipt_args = [
        "receipt",
        "--baseline",
        str(baseline_paths[0]),
        "--baseline",
        str(baseline_paths[1]),
        "--verification",
        str(verification_dir / "report.json"),
        "--issue-file",
        str(issue),
        "--repo-root",
        str(repo),
        "--output",
        str(receipt_dir),
    ]
    if trace is not None:
        receipt_args.extend(["--trace", str(trace)])
    receipt_args.extend(["--check-report", str(check_dir / "report.json")])
    receipt_args.extend(["--identity-mode", "github"])
    if main(receipt_args) != 0:
        raise RuntimeError("receipt returned a non-zero IssueProof status")

    receipt = load_receipt(receipt_dir / "receipt.json")
    if receipt.verdict != "verified":
        raise RuntimeError(f"unexpected receipt verdict: {receipt.verdict}")
    if trace is None and receipt.trace_status != "absent":
        raise RuntimeError(f"unexpected no-trace status: {receipt.trace_status}")
    summary = {
        "repo": str(repo),
        "receipt": str(receipt_dir / "receipt.json"),
        "markdown": str(receipt_dir / "receipt.md"),
        "verdict": receipt.verdict,
        "trace_status": receipt.trace_status,
        "baseline_group": receipt.baseline_group,
        "report_hashes": receipt.report_hashes,
    }
    (output_dir / "session-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main_script() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    args = parser.parse_args()
    summary = _run(args.output_dir.resolve(), args.trace.resolve() if args.trace else None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_script())
