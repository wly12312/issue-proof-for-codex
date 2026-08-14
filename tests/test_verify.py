import subprocess
import sys
from pathlib import Path

from issue_proof.collector import collect_from_issue_file
from issue_proof.executor import ExecutionLimits
from issue_proof.verify import verify_against_baseline, verify_argv_against_baseline


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def baseline(tmp_path: Path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "issue-proof@example.invalid"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "IssueProof Test"],
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "https://github.com/example/verify-fixture.git",
        ],
        check=True,
        capture_output=True,
    )
    issue = tmp_path / "issue.md"
    issue.write_text("# Verify bug\n", encoding="utf-8")
    command = python_command(
        "import pathlib,sys; sys.exit(1 if not pathlib.Path('fixed.marker').exists() else 0)"
    )
    report, _, _ = collect_from_issue_file(
        issue_file=issue,
        repo_root=tmp_path,
        command=command,
        output_dir=tmp_path / "baseline",
        limits=ExecutionLimits(timeout_seconds=5),
        identity_mode="github",
    )
    return report, command


def test_verify_classifies_fix_conservatively(tmp_path) -> None:
    report, command = baseline(tmp_path)
    (tmp_path / "fixed.marker").write_text("fixed", encoding="utf-8")
    fixed = verify_against_baseline(
        report,
        command=command,
        repo_root=tmp_path,
        limits=ExecutionLimits(timeout_seconds=5),
        identity_mode="github",
    )
    assert fixed.verification["outcome"] == "verified"
    assert fixed.verification["baseline_run_id"] == report.run_id


def test_verify_marks_still_failing_as_not_fixed(tmp_path) -> None:
    report, command = baseline(tmp_path)
    current = verify_against_baseline(
        report,
        command=command,
        repo_root=tmp_path,
        limits=ExecutionLimits(timeout_seconds=5),
        identity_mode="github",
    )
    assert current.verification["outcome"] == "not-fixed"


def test_verify_marks_non_reproduced_baseline_inconclusive(tmp_path) -> None:
    baseline_report, command = baseline(tmp_path)
    (tmp_path / "fixed.marker").write_text("fixed", encoding="utf-8")
    baseline_report.reproduction["outcome"] = "not-reproduced"
    baseline_report.execution.exit_code = 0
    current = verify_against_baseline(
        baseline_report,
        command=command,
        repo_root=tmp_path,
        identity_mode="github",
    )
    assert current.verification["outcome"] == "inconclusive"


def test_verify_rejects_reproduced_baseline_with_zero_exit(tmp_path) -> None:
    baseline_report, command = baseline(tmp_path)
    baseline_report.reproduction["outcome"] = "reproduced"
    baseline_report.execution.exit_code = 0
    argv = list(baseline_report.execution.argv)

    direct = verify_argv_against_baseline(
        baseline_report,
        argv=argv,
        execution={"exit_code": 0, "timed_out": False},
        repo_root=tmp_path,
    )
    assert direct["verification"]["outcome"] == "inconclusive"

    (tmp_path / "fixed.marker").write_text("fixed", encoding="utf-8")
    current = verify_against_baseline(
        baseline_report,
        command=command,
        repo_root=tmp_path,
    )
    assert current.verification["outcome"] == "inconclusive"


def test_direct_verification_rejects_a_different_repository(tmp_path) -> None:
    baseline_root = tmp_path / "baseline repo"
    verification_root = tmp_path / "verification repo"
    baseline_root.mkdir()
    verification_root.mkdir()
    baseline_report, _ = baseline(baseline_root)

    result = verify_argv_against_baseline(
        baseline_report,
        argv=list(baseline_report.execution.argv),
        execution={"exit_code": 0, "timed_out": False},
        repo_root=verification_root,
        identity_mode="local",
    )

    assert result["verification"]["outcome"] == "inconclusive"
    assert "repository" in result["verification"]["reason"].lower()
