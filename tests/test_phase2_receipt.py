import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from issue_proof.cli import main
from issue_proof.codex.parser import ParseLimits, parse_trace
from issue_proof.codex.receipt import build_report_receipt, load_receipt, validate_receipt_dict
from issue_proof.collector import write_report_files
from issue_proof.errors import SchemaValidationError
from issue_proof.identity import argv_identity, cwd_identity, file_sha256, timeout_policy_identity
from issue_proof.models import load_report
from issue_proof.verify import verify_argv_against_baseline


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, list[str]]:
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "issue-proof@example.invalid")
    _git(repo, "config", "user.name", "IssueProof Test")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "fixture")
    _git(repo, "remote", "add", "origin", "https://github.com/example/phase2-fixture.git")
    issue = tmp_path / "issue.md"
    issue.write_text(
        "# Phase 2 fixture\n\nThe command fails before the marker exists.\n",
        encoding="utf-8",
    )
    command_argv = [
        sys.executable,
        "-c",
        "import pathlib,sys; sys.exit(1 if not pathlib.Path('fixed.marker').exists() else 0)",
    ]
    command_file = tmp_path / "command-argv.json"
    command_file.write_text(json.dumps(command_argv), encoding="utf-8")
    return repo, issue, command_file, command_argv


def _collect_and_verify(tmp_path: Path):
    repo, issue, command_file, command_argv = _fixture(tmp_path)
    baseline_dirs = [tmp_path / "baseline-1", tmp_path / "baseline-2"]
    for output in baseline_dirs:
        assert (
            main(
                [
                    "collect",
                    "--issue-file",
                    str(issue),
                    "--command-argv",
                    str(command_file),
                    "--output",
                    str(output),
                    "--repo-root",
                    str(repo),
                    "--identity-mode",
                    "github",
                ]
            )
            == 0
        )
    baseline_paths = [output / "report.json" for output in baseline_dirs]
    (repo / "fixed.marker").write_text("fixed\n", encoding="utf-8")
    verification_dir = tmp_path / "verification"
    assert (
        main(
            [
                "verify",
                "--baseline",
                str(baseline_paths[0]),
                "--command-argv",
                str(command_file),
                "--output",
                str(verification_dir),
                "--repo-root",
                str(repo),
                "--identity-mode",
                "github",
            ]
        )
        == 0
    )
    return repo, issue, command_argv, baseline_paths, verification_dir / "report.json"


def test_phase2_cli_receipt_is_verified_without_trace(tmp_path) -> None:
    repo, issue, _, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    output = tmp_path / "receipt"
    assert (
        main(
            [
                "receipt",
                "--baseline",
                str(baseline_paths[0]),
                "--baseline",
                str(baseline_paths[1]),
                "--verification",
                str(verification_path),
                "--issue-file",
                str(issue),
                "--repo-root",
                str(repo),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    receipt = load_receipt(output / "receipt.json")
    data = receipt.as_dict()
    assert receipt.verdict == "verified"
    assert data["receipt_mode"] == "core-verification"
    assert data["trace_status"] == "absent"
    assert data["trace"]["status"] == "absent"
    assert any("trace-not-supplied" in warning for warning in data["warnings"])
    assert data["baseline_group"]["stability"] == "stable"
    assert data["baseline_group"]["run_count"] == 2
    assert data["verification"]["outcome"] == "verified"
    assert all(
        data["verification"][key] is True
        for key in (
            "same_argv",
            "same_cwd",
            "same_repository",
            "same_remote",
            "same_head",
            "same_timeout",
            "same_termination_policy",
            "same_timeout_policy",
            "same_runtime",
            "same_tool",
        )
    )
    assert any(
        claim["type"] == "fix-verified" and claim["status"] == "supported"
        for claim in data["claims"]
    )
    assert data["report_hashes"]["verification"]
    assert data["verification"]["baseline_report_sha256"] == file_sha256(baseline_paths[0])
    assert (output / "receipt.md").exists()
    assert main(["validate", str(output / "receipt.json")]) == 0

    trace_claim_receipt = build_report_receipt(
        [load_report(path) for path in baseline_paths],
        load_report(verification_path),
        repo_root=repo,
        claim_inputs=[{"id": "trace-tests", "type": "tests-passed", "evidence_ids": ["trace"]}],
    )
    assert trace_claim_receipt.verdict == "verified"
    assert trace_claim_receipt.claims[0]["status"] == "unverified"

    tampered = data.copy()
    tampered["verification"] = dict(data["verification"])
    tampered["verification"]["verification_report_sha256"] = "0" * 64
    with pytest.raises(SchemaValidationError, match="verification report hash"):
        validate_receipt_dict(tampered)


def test_phase2_receipt_requires_two_stable_baselines(tmp_path) -> None:
    repo, _, _, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    baseline = load_report(baseline_paths[0])
    verification = load_report(verification_path)
    receipt = build_report_receipt([baseline], verification, repo_root=repo)
    assert receipt.verdict == "inconclusive"
    assert receipt.baseline_group["stability"] == "single-run"
    assert receipt.verification["outcome"] == "inconclusive"


def test_phase2_verification_marks_identity_mismatches_inconclusive(tmp_path) -> None:
    repo, _, command_argv, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    baseline = load_report(baseline_paths[0])
    verification = load_report(verification_path)

    changed_cwd = verification.execution.as_dict()
    other_cwd = tmp_path / "other cwd"
    other_cwd.mkdir()
    changed_cwd["cwd"] = str(other_cwd)
    changed_cwd["cwd_identity"] = cwd_identity(other_cwd)
    cwd_result = verify_argv_against_baseline(
        baseline, argv=command_argv, execution=changed_cwd, repo_root=repo
    )
    assert cwd_result["verification"]["outcome"] == "inconclusive"
    assert cwd_result["verification"]["same_cwd"] is False

    changed_argv = verification.execution.as_dict()
    other_argv = [*command_argv[:-1], command_argv[-1] + " "]
    changed_argv["argv"] = other_argv
    changed_argv["argv_identity"] = argv_identity(other_argv)
    argv_result = verify_argv_against_baseline(
        baseline, argv=other_argv, execution=changed_argv, repo_root=repo
    )
    assert argv_result["verification"]["outcome"] == "inconclusive"
    assert argv_result["verification"]["same_argv"] is False

    changed_timeout = verification.execution.as_dict()
    changed_timeout["timeout_seconds"] = 1.0
    changed_timeout["timeout_policy_identity"] = timeout_policy_identity(
        1.0,
        changed_timeout["termination_policy"],
        changed_timeout["capture_limits"],
    )
    timeout_result = verify_argv_against_baseline(
        baseline, argv=command_argv, execution=changed_timeout, repo_root=repo
    )
    assert timeout_result["verification"]["outcome"] == "inconclusive"
    assert timeout_result["verification"]["same_timeout"] is False

    changed_remote = deepcopy(baseline)
    changed_remote.repository.remote_url = "https://example.invalid/other.git"
    remote_result = verify_argv_against_baseline(
        changed_remote,
        argv=command_argv,
        execution=verification.execution.as_dict(),
        repo_root=repo,
    )
    assert remote_result["verification"]["outcome"] == "inconclusive"
    assert remote_result["verification"]["same_remote"] is False

    changed_head = deepcopy(baseline)
    changed_head.repository.head_sha = "0" * 40
    head_result = verify_argv_against_baseline(
        changed_head,
        argv=command_argv,
        execution=verification.execution.as_dict(),
        repo_root=repo,
    )
    assert head_result["verification"]["outcome"] == "inconclusive"
    assert head_result["verification"]["same_head"] is False

    changed_repository = deepcopy(baseline)
    changed_repository.repository.root = str(tmp_path / "different-repository")
    repository_result = verify_argv_against_baseline(
        changed_repository,
        argv=command_argv,
        execution=verification.execution.as_dict(),
        repo_root=repo,
    )
    assert repository_result["verification"]["outcome"] == "inconclusive"
    assert repository_result["verification"]["same_repository"] is False

    changed_runtime = deepcopy(baseline)
    changed_runtime.runtime.versions["python"] = "different-runtime"
    runtime_result = verify_argv_against_baseline(
        changed_runtime,
        argv=command_argv,
        execution=verification.execution.as_dict(),
        repo_root=repo,
    )
    assert runtime_result["verification"]["outcome"] == "inconclusive"
    assert runtime_result["verification"]["same_runtime"] is False


def test_phase2_trace_is_optional_and_only_trace_status_changes(tmp_path) -> None:
    repo, _, _, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    baseline_reports = [load_report(path) for path in baseline_paths]
    verification = load_report(verification_path)
    trace_path = (
        Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    )
    valid = build_report_receipt(
        baseline_reports,
        verification,
        repo_root=repo,
        trace=parse_trace(trace_path),
    )
    assert valid.verdict == "verified"
    assert valid.trace_status == "present"

    corrupt_path = tmp_path / "corrupt.jsonl"
    corrupt_path.write_text("not-json\n", encoding="utf-8")
    corrupt = build_report_receipt(
        baseline_reports,
        verification,
        repo_root=repo,
        trace=parse_trace(corrupt_path),
    )
    assert corrupt.verdict == "verified"
    assert corrupt.trace_status == "invalid"
    assert corrupt.trace["status"] == "invalid"

    truncated = build_report_receipt(
        baseline_reports,
        verification,
        repo_root=repo,
        trace=parse_trace(trace_path, limits=ParseLimits(max_events=1)),
    )
    assert truncated.verdict == "verified"
    assert truncated.trace_status == "truncated"
    assert truncated.trace["status"] == "truncated"


def test_phase2_receipt_can_include_structured_check_reports(tmp_path) -> None:
    repo, issue, _, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    check = load_report(verification_path)
    output = tmp_path / "receipt-with-check"
    receipt = build_report_receipt(
        [load_report(path) for path in baseline_paths],
        check,
        repo_root=repo,
        issue={"source": "local-file", "location": str(issue)},
        check_reports=[check],
    )
    assert receipt.checks[0]["purpose"] == "additional-regression-check"
    assert receipt.checks[0]["outcome"] == "passed"
    assert "runtime_identity" in receipt.checks[0]
    assert "stdout" in receipt.checks[0] and "stderr" in receipt.checks[0]
    write_report_files(check, output / "check-report")

    failed_check = deepcopy(check)
    failed_check.verification["outcome"] = "not-fixed"
    failed_check.execution.exit_code = 1
    failed_receipt = build_report_receipt(
        [load_report(path) for path in baseline_paths],
        check,
        repo_root=repo,
        check_reports=[failed_check],
    )
    assert failed_receipt.verdict == "partially-verified"
    assert any("check-0001" in warning for warning in failed_receipt.warnings)

    inconclusive_check = deepcopy(check)
    inconclusive_check.verification["outcome"] = "not-applicable"
    inconclusive_check.reproduction["outcome"] = "inconclusive"
    inconclusive_check.execution.timed_out = True
    inconclusive_check.execution.exit_code = None
    inconclusive_receipt = build_report_receipt(
        [load_report(path) for path in baseline_paths],
        check,
        repo_root=repo,
        check_reports=[inconclusive_check],
    )
    assert inconclusive_receipt.checks[0]["outcome"] == "inconclusive"


def test_phase2_collection_report_is_a_passed_check_only_after_exit_zero(tmp_path) -> None:
    repo, issue, command_argv, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    command_file = tmp_path / "check-command.json"
    command_file.write_text(json.dumps(command_argv), encoding="utf-8")
    check_dir = tmp_path / "collection-check"
    assert (
        main(
            [
                "collect",
                "--issue-file",
                str(issue),
                "--command-argv",
                str(command_file),
                "--repo-root",
                str(repo),
                "--identity-mode",
                "github",
                "--output",
                str(check_dir),
            ]
        )
        == 0
    )
    check = load_report(check_dir / "report.json")
    assert check.verification["outcome"] == "not-applicable"
    assert check.reproduction["outcome"] == "not-reproduced"
    receipt = build_report_receipt(
        [load_report(path) for path in baseline_paths],
        load_report(verification_path),
        repo_root=repo,
        check_reports=[check],
    )
    assert receipt.checks[0]["outcome"] == "passed"
    assert receipt.checks[0]["status"] == "passed"
    assert receipt.checks[0]["source_outcome"] == "not-applicable"


def test_phase2_receipt_downgrades_missing_remote_or_head(tmp_path) -> None:
    repo, _, _, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    baselines = [load_report(path) for path in baseline_paths]
    verification = load_report(verification_path)
    for report in [*baselines, verification]:
        report.repository.remote_url = None
        report.repository.head_sha = None
        report.repository.identity_mode = "local"
    receipt = build_report_receipt(
        baselines,
        verification,
        repo_root=repo,
        identity_mode="local",
    )
    assert receipt.verdict == "inconclusive"
    assert receipt.baseline_group["same_remote"] is None
    assert receipt.baseline_group["same_head"] is None
    assert receipt.verification["same_remote"] is None
    assert receipt.verification["same_head"] is None
    assert receipt.verification["identity_complete"] is False
    assert any("missing remote or HEAD" in warning for warning in receipt.warnings)


def test_phase2_receipt_recomputes_identity_instead_of_trusting_same_fields(tmp_path) -> None:
    repo, _, _, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    baselines = [load_report(path) for path in baseline_paths]
    verification = load_report(verification_path)
    for key in (
        "same_argv",
        "same_cwd",
        "same_repository",
        "same_remote",
        "same_head",
        "same_timeout",
        "same_termination_policy",
        "same_timeout_policy",
        "same_runtime",
        "same_tool",
    ):
        verification.verification[key] = False
    verification.verification["identity_complete"] = False
    receipt = build_report_receipt(baselines, verification, repo_root=repo)
    assert receipt.verdict == "verified"
    assert all(
        receipt.verification[key] is True
        for key in (
            "same_argv",
            "same_cwd",
            "same_repository",
            "same_remote",
            "same_head",
            "same_timeout",
            "same_termination_policy",
            "same_timeout_policy",
            "same_runtime",
            "same_tool",
        )
    )


def test_phase2_receipt_detects_replaced_baseline_report(tmp_path) -> None:
    repo, _, _, baseline_paths, verification_path = _collect_and_verify(tmp_path)
    replaced = load_report(baseline_paths[0])
    replaced.execution.argv[-1] += " tampered"
    receipt = build_report_receipt(
        [replaced, load_report(baseline_paths[1])],
        load_report(verification_path),
        repo_root=repo,
    )
    assert receipt.verdict == "inconclusive"
    assert receipt.verification["baseline_report_hash_match"] is False


def test_phase2_github_identity_mode_rejects_missing_remote(tmp_path) -> None:
    repo, issue, command_file, _ = _fixture(tmp_path)
    _git(repo, "remote", "remove", "origin")
    assert (
        main(
            [
                "collect",
                "--issue-file",
                str(issue),
                "--command-argv",
                str(command_file),
                "--repo-root",
                str(repo),
                "--identity-mode",
                "github",
                "--output",
                str(tmp_path / "strict-baseline"),
            ]
        )
        == 4
    )
