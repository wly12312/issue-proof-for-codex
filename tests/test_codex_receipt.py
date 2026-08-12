import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from issue_proof.codex.git_provenance import MAX_CHANGED_FILES
from issue_proof.codex.parser import ParseLimits, parse_trace
from issue_proof.codex.receipt import (
    RECEIPT_SCHEMA_VERSION,
    build_receipt,
    render_receipt,
    validate_receipt_dict,
)
from issue_proof.errors import SchemaValidationError


def test_receipt_is_versioned_redacted_and_cites_evidence(tmp_path) -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    summary = parse_trace(trace)
    receipt = build_receipt(
        summary,
        repo_root=tmp_path,
        issue={"source": "github-url", "url": "https://github.com/example/repo/issues/7"},
        claim_inputs=[
            {"id": "baseline", "type": "bug-reproduced", "evidence_ids": ["baseline-reproduction"]}
        ],
    )
    data = receipt.as_dict()
    validate_receipt_dict(data)
    assert data["receipt_type"] == "CodexMaintenanceReceipt"
    assert data["receipt_schema_version"] == RECEIPT_SCHEMA_VERSION
    assert data["codex"]["raw_trace_persisted"] is False
    assert data["issue"]["number"] == 7
    assert all("token=ghp_" not in json.dumps(item) for item in data["commands"])
    assert data["claims"][0]["evidence_ids"] == ["baseline-reproduction"]
    assert data["claims"][0]["status"] == "unverified"
    assert "baseline-reproduction" not in {item["id"] for item in data["evidence"]}
    markdown = render_receipt(receipt)
    assert markdown.startswith("# Codex Maintenance Receipt\n")
    assert "baseline-reproduction" in markdown


def test_receipt_without_baseline_does_not_claim_fix_verified(tmp_path) -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-b.jsonl"
    receipt = build_receipt(parse_trace(trace), repo_root=tmp_path)
    assert receipt.verdict in {"unverified", "inconclusive"}
    assert all(claim["type"] != "fix-verified" for claim in receipt.as_dict()["claims"])


def test_receipt_redacts_absolute_execution_paths(tmp_path) -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-b.jsonl"
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced", "reason": "exit 1", "stability": "single-run"},
        "execution": {
            "argv": [r"C:\Users\person\repo\python.exe", "tests/test_bug.py"],
            "display_command": r"C:\Users\person\repo\python.exe tests/test_bug.py",
            "cwd": r"C:\Users\person\repo",
            "exit_code": 1,
            "timed_out": False,
        },
    }
    receipt = build_receipt(parse_trace(trace), repo_root=tmp_path, baseline=baseline)
    execution = receipt.as_dict()["baseline"]["execution"]
    assert execution["cwd"] == "<absolute-path>"
    assert execution["argv"][0] == "<absolute-path>"
    assert r"C:\Users\person" not in execution["display_command"]
    assert "C:\\Users\\person" not in receipt.to_json()


def test_receipt_limits_changed_files_and_keeps_complete_digest(tmp_path) -> None:
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    total = MAX_CHANGED_FILES + 17
    for index in range(total):
        (tmp_path / f"changed-{index:04d}.txt").write_text("change", encoding="utf-8")
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-b.jsonl"

    receipt = build_receipt(parse_trace(trace), repo_root=tmp_path)
    data = receipt.as_dict()
    repository = data["repository"]

    assert repository["changed_files_total"] == total
    assert repository["changed_files_recorded"] == MAX_CHANGED_FILES
    assert repository["changed_files_truncated"] is True
    assert repository["changed_files_overflow"] is True
    assert len(repository["changed_files_sha256"]) == 64
    assert any("entry limit" in warning for warning in data["warnings"])
    assert "changed-0319.txt" not in "\n".join(data["warnings"])
    assert len(receipt.to_json().encode("utf-8")) < 100_000


def test_receipt_downgrades_when_trace_event_limit_truncates_evidence(tmp_path) -> None:
    trace_path = tmp_path / "limited.jsonl"
    trace_path.write_text(
        '{"type":"thread.started","thread_id":"one"}\n{"type":"turn.completed"}\n',
        encoding="utf-8",
    )
    summary = parse_trace(trace_path, limits=ParseLimits(max_events=1))
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced"},
        "execution": {"argv": ["verify"], "exit_code": 1, "timed_out": False},
    }
    verification = {
        "verification": {
            "outcome": "verified",
            "reason": "passed",
            "baseline_run_id": "baseline-run",
        }
    }
    command = {"argv": ["verify"], "exit_code": 0, "timed_out": False}

    receipt = build_receipt(
        summary,
        baseline=baseline,
        verification=verification,
        verification_command=command,
    )

    assert receipt.verdict == "inconclusive"
    assert receipt.as_dict()["trace"]["event_limit_reached"] is True


def test_receipt_validator_rejects_unknown_root_fields() -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    data = build_receipt(parse_trace(trace)).as_dict()
    data["unexpected"] = True

    with pytest.raises(SchemaValidationError, match="unexpected"):
        validate_receipt_dict(data)


def test_receipt_validator_enforces_codex_and_trace_schema_constraints() -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    base = build_receipt(parse_trace(trace)).as_dict()
    cases = []
    data = deepcopy(base)
    data["codex"]["unexpected"] = True
    cases.append(data)
    data = deepcopy(base)
    data["codex"]["raw_trace_persisted"] = True
    cases.append(data)
    data = deepcopy(base)
    data["repository"] = []
    cases.append(data)
    data = deepcopy(base)
    data["trace"]["event_limit_reached"] = "yes"
    cases.append(data)
    data = deepcopy(base)
    data["tool_version"] = ""
    cases.append(data)

    for data in cases:
        with pytest.raises(SchemaValidationError):
            validate_receipt_dict(data)


@pytest.mark.parametrize(
    ("command", "reason_fragment"),
    [
        ({"argv": ["different"], "exit_code": 0, "timed_out": False}, "argv"),
        ({"argv": ["verify"], "exit_code": 1, "timed_out": False}, "exit"),
        ({"argv": ["verify"], "exit_code": None, "timed_out": True}, "timeout"),
    ],
)
def test_receipt_rejects_verified_outcome_that_conflicts_with_command(
    command, reason_fragment
) -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced"},
        "execution": {"argv": ["verify"], "exit_code": 1, "timed_out": False},
    }
    verification = {
        "verification": {
            "outcome": "verified",
            "reason": "claimed pass",
            "baseline_run_id": "baseline-run",
        }
    }

    receipt = build_receipt(
        parse_trace(trace),
        baseline=baseline,
        verification=verification,
        verification_command=command,
    )

    assert receipt.verdict == "inconclusive"
    assert receipt.verification["outcome"] == "inconclusive"
    assert reason_fragment in receipt.verification["reason"].lower()


@pytest.mark.parametrize(
    ("baseline", "expected_verdict"),
    [
        (
            {
                "run_id": "baseline-run",
                "reproduction": {"outcome": "not-reproduced"},
                "execution": {"argv": ["verify"], "exit_code": 0, "timed_out": False},
            },
            "refuted",
        ),
        (
            {
                "run_id": "baseline-run",
                "reproduction": {"outcome": "reproduced"},
                "execution": {"argv": ["verify"], "exit_code": 0, "timed_out": False},
            },
            "inconclusive",
        ),
        (
            {
                "run_id": "baseline-run",
                "reproduction": {"outcome": "reproduced"},
                "execution": {"argv": ["verify"], "exit_code": None, "timed_out": True},
            },
            "inconclusive",
        ),
    ],
)
def test_receipt_rejects_verified_outcome_with_invalid_baseline(baseline, expected_verdict) -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    verification = {
        "verification": {
            "outcome": "verified",
            "reason": "claimed pass",
            "baseline_run_id": "baseline-run",
        }
    }
    command = {"argv": ["verify"], "exit_code": 0, "timed_out": False}

    receipt = build_receipt(
        parse_trace(trace),
        baseline=baseline,
        verification=verification,
        verification_command=command,
    )

    assert receipt.verdict == expected_verdict
    assert receipt.verification["outcome"] == "inconclusive"
    assert "baseline" in receipt.verification["reason"].lower()


def test_claim_command_evidence_id_exists_in_receipt_evidence() -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced"},
        "execution": {"argv": ["verify"], "exit_code": 1, "timed_out": False},
    }
    verification = {
        "verification": {
            "outcome": "verified",
            "reason": "passed",
            "baseline_run_id": "baseline-run",
        }
    }
    command = {"argv": ["verify"], "exit_code": 0, "timed_out": False}
    receipt = build_receipt(
        parse_trace(trace),
        baseline=baseline,
        verification=verification,
        verification_command=command,
        claim_inputs=[
            {
                "id": "tests",
                "type": "tests-passed",
                "evidence_ids": ["verification-command"],
            }
        ],
    )

    evidence_ids = {item["id"] for item in receipt.evidence}
    assert receipt.claims[0]["status"] == "supported"
    assert set(receipt.claims[0]["evidence_ids"]) <= evidence_ids


def test_receipt_compares_raw_argv_before_absolute_path_redaction() -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced"},
        "execution": {
            "argv": [r"C:\baseline\verify.exe"],
            "exit_code": 1,
            "timed_out": False,
        },
    }
    verification = {
        "verification": {
            "outcome": "verified",
            "reason": "claimed pass",
            "baseline_run_id": "baseline-run",
        }
    }
    command = {"argv": [r"D:\different\verify.exe"], "exit_code": 0, "timed_out": False}

    receipt = build_receipt(
        parse_trace(trace),
        baseline=baseline,
        verification=verification,
        verification_command=command,
    )

    assert receipt.verification["same_argv"] is False
    assert receipt.verification["outcome"] == "inconclusive"
    assert receipt.verdict == "inconclusive"


def test_receipt_rejects_verification_for_a_different_baseline_run() -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    baseline = {
        "run_id": "baseline-a",
        "reproduction": {"outcome": "reproduced"},
        "execution": {"argv": ["verify"], "exit_code": 1, "timed_out": False},
    }
    verification = {
        "verification": {
            "outcome": "verified",
            "reason": "claimed pass",
            "baseline_run_id": "baseline-b",
        }
    }
    command = {"argv": ["verify"], "exit_code": 0, "timed_out": False}

    receipt = build_receipt(
        parse_trace(trace),
        baseline=baseline,
        verification=verification,
        verification_command=command,
    )

    assert receipt.verification["outcome"] == "inconclusive"
    assert "baseline run" in receipt.verification["reason"].lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generated_at", "not-a-date"),
        ("issue", []),
        ("verification", []),
        ("agents", []),
        ("commands", [1]),
        ("evidence", [None]),
        ("claims", ["claim"]),
        ("warnings", [1]),
        ("parse_errors", ["error"]),
    ],
)
def test_receipt_validator_rejects_values_forbidden_by_repository_schema(field, value) -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    data = build_receipt(parse_trace(trace)).as_dict()
    data[field] = value

    with pytest.raises(SchemaValidationError):
        validate_receipt_dict(data)


def test_empty_trace_cannot_produce_verified_receipt(tmp_path) -> None:
    trace_path = tmp_path / "empty.jsonl"
    trace_path.write_text("", encoding="utf-8")
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced"},
        "execution": {"argv": ["verify"], "exit_code": 1, "timed_out": False},
    }
    verification = {
        "verification": {
            "outcome": "verified",
            "reason": "claimed pass",
            "baseline_run_id": "baseline-run",
        }
    }

    receipt = build_receipt(
        parse_trace(trace_path),
        baseline=baseline,
        verification=verification,
        verification_command={"argv": ["verify"], "exit_code": 0, "timed_out": False},
    )

    assert receipt.verdict == "inconclusive"


def test_truncated_trace_takes_precedence_over_direct_refutation(tmp_path) -> None:
    trace_path = tmp_path / "limited.jsonl"
    trace_path.write_text(
        '{"type":"thread.started","thread_id":"one"}\n{"type":"turn.completed"}\n',
        encoding="utf-8",
    )
    summary = parse_trace(trace_path, limits=ParseLimits(max_events=1))

    receipt = build_receipt(
        summary,
        verification={
            "verification": {
                "outcome": "not-fixed",
                "reason": "claimed failure",
                "baseline_run_id": "baseline-run",
            }
        },
    )

    assert summary.event_limit_reached is True
    assert receipt.verdict == "inconclusive"


def test_receipt_stream_metadata_describes_persisted_sanitized_summary() -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced"},
        "execution": {
            "argv": ["verify"],
            "exit_code": 1,
            "timed_out": False,
            "stdout": {
                "summary": "token=super-secret",
                "sha256": "0" * 64,
                "captured_bytes": 18,
                "truncated": False,
                "redacted": False,
            },
        },
    }

    receipt = build_receipt(parse_trace(trace), baseline=baseline)
    stream = receipt.baseline["execution"]["stdout"]
    persisted = stream["summary"]

    assert persisted == "token=[REDACTED]"
    assert stream["sha256"] == hashlib.sha256(persisted.encode("utf-8")).hexdigest()
    assert stream["captured_bytes"] == len(persisted.encode("utf-8"))
    assert stream["redacted"] is True


@pytest.mark.parametrize(
    ("argv", "cwd"),
    [
        ([r"C:private\runner.exe"], r"\Users\person"),
        ([r"\\?\C:\Users\person\runner.exe"], r"\\server\share\person"),
        (["/private/runner"], "/Users/person"),
    ],
)
def test_receipt_projects_all_rooted_or_drive_qualified_windows_paths(argv, cwd) -> None:
    trace = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"
    baseline = {
        "run_id": "baseline-run",
        "reproduction": {"outcome": "reproduced"},
        "execution": {"argv": argv, "cwd": cwd, "exit_code": 1, "timed_out": False},
    }

    receipt = build_receipt(parse_trace(trace), baseline=baseline)
    execution = receipt.baseline["execution"]

    assert execution["argv"] == ["<absolute-path>"]
    assert execution["cwd"] == "<absolute-path>"


def test_trace_command_paths_are_projected_before_receipt_persistence(tmp_path) -> None:
    trace = tmp_path / "absolute-command.jsonl"
    trace.write_text(
        json.dumps(
            {
                "type": "command_execution",
                "argv": [r"C:\Users\alice\private\runner.exe", r"\\server\share\input.txt"],
                "display_command": (r"C:\Users\alice\private\runner.exe \\server\share\input.txt"),
                "cwd": r"C:\Users\alice\private",
                "exit_code": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    receipt = build_receipt(parse_trace(trace))
    serialized = receipt.to_json()
    command = receipt.commands[0]

    assert command["argv"] == ["<absolute-path>", "<absolute-path>"]
    assert command["cwd"] == "<absolute-path>"
    assert "alice" not in serialized
    assert "server" not in serialized
