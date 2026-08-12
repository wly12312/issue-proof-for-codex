import json
from pathlib import Path

from issue_proof.codex.git_provenance import MAX_CHANGED_FILES
from issue_proof.codex.parser import parse_trace
from issue_proof.codex.receipt import (
    RECEIPT_SCHEMA_VERSION,
    build_receipt,
    render_receipt,
    validate_receipt_dict,
)


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
