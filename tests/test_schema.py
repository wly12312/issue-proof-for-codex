import json
from copy import deepcopy
from pathlib import Path

import pytest

from issue_proof.errors import SchemaValidationError
from issue_proof.models import validate_report_dict


def test_schema_file_is_versioned_and_has_required_sections() -> None:
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "issue-proof.schema.json").read_text()
    )
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"
    assert set(schema["required"]) >= {
        "issue",
        "repository",
        "runtime",
        "execution",
        "reproduction",
        "verification",
    }

    receipt_schema = json.loads(
        (
            Path(__file__).parents[1] / "schemas" / "codex-maintenance-receipt.schema.json"
        ).read_text()
    )
    assert receipt_schema["properties"]["receipt_type"]["const"] == "CodexMaintenanceReceipt"
    assert receipt_schema["properties"]["receipt_schema_version"]["const"] == "2.0.0"
    assert set(receipt_schema["required"]) >= {
        "baseline_group",
        "checks",
        "report_hashes",
        "receipt_mode",
        "trace_status",
    }
    assert "identity" in receipt_schema["properties"]["repository"]["required"]


def test_schema_validator_rejects_bad_hash_and_outcome() -> None:
    with pytest.raises(SchemaValidationError):
        validate_report_dict(
            {
                "schema_version": "1.0.0",
                "tool_version": "0.1.0",
                "run_id": "run",
                "created_at": "2026-01-01T00:00:00Z",
                "issue": {
                    "source": "local-file",
                    "location": "issue.md",
                    "url": None,
                    "title": "x",
                    "body_summary_hash": "bad",
                    "body_excerpt": "x",
                },
                "repository": {
                    "root": ".",
                    "remote_url": None,
                    "head_sha": None,
                    "branch": None,
                    "dirty": None,
                },
                "runtime": {
                    "os": "Windows",
                    "architecture": "AMD64",
                    "versions": {"python": "3.12"},
                },
                "execution": {
                    "argv": [],
                    "display_command": None,
                    "cwd": None,
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": None,
                    "exit_code": None,
                    "timed_out": False,
                    "stdout": {
                        "summary": "",
                        "sha256": "0" * 64,
                        "captured_bytes": 0,
                        "truncated": False,
                        "redacted": False,
                    },
                    "stderr": {
                        "summary": "",
                        "sha256": "0" * 64,
                        "captured_bytes": 0,
                        "truncated": False,
                        "redacted": False,
                    },
                },
                "artifacts": [],
                "reproduction": {"outcome": "wrong"},
                "verification": {"outcome": "not-applicable"},
                "warnings": [],
                "security_events": [],
                "notes": [],
            }
        )


def test_old_report_shape_remains_valid_when_codex_is_absent(tmp_path) -> None:
    from issue_proof.collector import collect_from_issue_file
    from issue_proof.models import load_report

    issue = Path(__file__).parent / "fixtures" / "issue.md"
    report, json_path, _ = collect_from_issue_file(
        issue_file=issue,
        repo_root=Path(__file__).parents[1],
        command=None,
        output_dir=tmp_path / "schema-compat-output",
    )
    loaded = load_report(json_path)
    assert loaded.codex is None
    assert "codex" not in report.as_dict()


def test_report_accepts_additive_codex_fragment(tmp_path) -> None:
    from issue_proof.collector import collect_from_issue_file
    from issue_proof.models import validate_report_dict

    report, _, _ = collect_from_issue_file(
        issue_file=Path(__file__).parent / "fixtures" / "issue.md",
        repo_root=Path(__file__).parents[1],
        command=None,
        output_dir=tmp_path / "codex-fragment",
    )
    report.codex = {"receipt_type": "CodexMaintenanceReceipt", "receipt_schema_version": "1.0.0"}
    data = report.as_dict()
    validate_report_dict(data)
    assert data["codex"]["receipt_type"] == "CodexMaintenanceReceipt"


def test_report_validator_rejects_unknown_root_fields(tmp_path) -> None:
    from issue_proof.collector import collect_from_issue_file

    report, _, _ = collect_from_issue_file(
        issue_file=Path(__file__).parent / "fixtures" / "issue.md",
        repo_root=Path(__file__).parents[1],
        command=None,
        output_dir=tmp_path / "unknown-report-field",
    )
    data = report.as_dict()
    data["unexpected"] = True

    with pytest.raises(SchemaValidationError, match="unexpected"):
        validate_report_dict(data)


def test_report_validator_enforces_nested_schema_constraints(tmp_path) -> None:
    from issue_proof.collector import collect_from_issue_file

    report, _, _ = collect_from_issue_file(
        issue_file=Path(__file__).parent / "fixtures" / "issue.md",
        repo_root=Path(__file__).parents[1],
        command=None,
        output_dir=tmp_path / "nested-report-schema",
    )
    base = report.as_dict()
    cases = []
    for section in ("issue", "repository", "runtime", "execution"):
        data = deepcopy(base)
        data[section]["unexpected"] = True
        cases.append(data)
    data = deepcopy(base)
    data["execution"]["stdout"]["unexpected"] = True
    cases.append(data)
    data = deepcopy(base)
    data["artifacts"][0]["unexpected"] = True
    cases.append(data)
    data = deepcopy(base)
    data["execution"]["duration_seconds"] = -1
    cases.append(data)
    data = deepcopy(base)
    data["tool_version"] = ""
    cases.append(data)

    for data in cases:
        with pytest.raises(SchemaValidationError):
            validate_report_dict(data)


@pytest.mark.parametrize("path", [r"C:relative.txt", r"\rooted.txt"])
def test_report_validator_rejects_windows_rooted_artifact_paths(tmp_path, path) -> None:
    from issue_proof.collector import collect_from_issue_file

    report, _, _ = collect_from_issue_file(
        issue_file=Path(__file__).parent / "fixtures" / "issue.md",
        repo_root=Path(__file__).parents[1],
        command=None,
        output_dir=tmp_path / "artifact-path",
    )
    data = report.as_dict()
    data["artifacts"][0]["path"] = path

    with pytest.raises(SchemaValidationError):
        validate_report_dict(data)
