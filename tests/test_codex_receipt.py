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
    verification = {"verification": {"outcome": "verified", "reason": "passed"}}
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
    verification = {"verification": {"outcome": "verified", "reason": "claimed pass"}}

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
    verification = {"verification": {"outcome": "verified", "reason": "claimed pass"}}
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
    verification = {"verification": {"outcome": "verified", "reason": "passed"}}
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
