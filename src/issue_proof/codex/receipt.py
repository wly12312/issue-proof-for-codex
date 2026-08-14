"""Versioned CodexMaintenanceReceipt construction, validation, and Markdown rendering."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..collector import ensure_output_dir, safe_output_file
from ..errors import DependencyError, SchemaValidationError
from ..identity import (
    argv_identity,
    cwd_identity,
    repository_identity,
    runtime_identity,
    timeout_policy_identity,
    tool_identity,
)
from ..models import Report
from ..redact import REDACTION, redact_text, sha256_text
from .agents import AgentScan
from .claims import Claim, verify_claims
from .events import TraceSummary
from .git_provenance import GitProvenance, collect_git_provenance

RECEIPT_SCHEMA_VERSION = "2.0.0"
SUPPORTED_RECEIPT_SCHEMA_VERSIONS = {"1.0.0", RECEIPT_SCHEMA_VERSION}
RECEIPT_TYPE = "CodexMaintenanceReceipt"
RECEIPT_VERDICTS = {"verified", "partially-verified", "unverified", "refuted", "inconclusive"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_WINDOWS = re.compile(r"^(?:[A-Za-z]:|[\\/])")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_value(value: Any, limit: int = 2_048) -> str | None:
    if value is None:
        return None
    text = redact_text(str(value)).text
    text = "".join(char if char in "\t\n\r" or ord(char) >= 32 else "�" for char in text)
    if len(text) > limit:
        return text[:limit] + "\n[value truncated]"
    return text


def _safe_path_value(value: Any, limit: int = 1_024) -> str | None:
    text = _safe_value(value, limit)
    if not text:
        return text
    if text.startswith("<absolute-path>"):
        return "<absolute-path>"
    if _ABSOLUTE_WINDOWS.match(text) or text.startswith("/"):
        return "<absolute-path>"
    return text.replace("\\", "/")


def _public_execution(execution: dict[str, Any] | None, evidence_id: str) -> dict[str, Any] | None:
    if not isinstance(execution, dict):
        return None
    argv = execution.get("argv", [])
    if not isinstance(argv, list):
        argv = []

    def public_stream(value: Any, label: str) -> dict[str, Any]:
        stream = value if isinstance(value, dict) else {}
        raw_summary = str(stream.get("summary") or "")
        projected = redact_text(raw_summary)
        summary = _safe_value(raw_summary, 16_384) or ""
        return {
            "summary": summary,
            "sha256": sha256_text(summary),
            "captured_bytes": len(summary.encode("utf-8")),
            "truncated": bool(stream.get("truncated", False)) or len(projected.text) > 16_384,
            "redacted": bool(stream.get("redacted", False)) or projected.redacted,
            "source": label,
        }

    public_argv = [
        (
            _safe_path_value(item, 1_024)
            if _ABSOLUTE_WINDOWS.match(item) or item.startswith("/")
            else _safe_value(item, 1_024)
        )
        or ""
        for item in argv
        if isinstance(item, str)
    ]
    return {
        "id": evidence_id,
        "argv": public_argv,
        "display_command": subprocess.list2cmdline(public_argv) if public_argv else None,
        "cwd": _safe_path_value(execution.get("cwd"), 1_024),
        "exit_code": execution.get("exit_code")
        if isinstance(execution.get("exit_code"), int)
        else None,
        "duration_seconds": execution.get("duration_seconds")
        if isinstance(execution.get("duration_seconds"), (int, float))
        else None,
        "timed_out": bool(execution.get("timed_out", False)),
        "timeout_seconds": execution.get("timeout_seconds")
        if isinstance(execution.get("timeout_seconds"), (int, float))
        else None,
        "termination_policy": _safe_value(execution.get("termination_policy"), 128),
        "capture_limits": execution.get("capture_limits")
        if isinstance(execution.get("capture_limits"), dict)
        else None,
        "argv_identity": execution.get("argv_identity")
        if isinstance(execution.get("argv_identity"), str)
        else None,
        "cwd_identity": execution.get("cwd_identity")
        if isinstance(execution.get("cwd_identity"), str)
        else None,
        "timeout_policy_identity": execution.get("timeout_policy_identity")
        if isinstance(execution.get("timeout_policy_identity"), str)
        else None,
        "stdout": public_stream(execution.get("stdout"), "stdout"),
        "stderr": public_stream(execution.get("stderr"), "stderr"),
    }


def _report_data(value: Report | dict[str, Any] | None) -> dict[str, Any] | None:
    if isinstance(value, Report):
        return value.as_dict()
    return value if isinstance(value, dict) else None


def _exact_argv(execution: Any) -> list[str] | None:
    if not isinstance(execution, dict):
        return None
    argv = execution.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) for item in argv)
        or not argv[0]
        or any(REDACTION in item for item in argv)
        or any(redact_text(item).redacted for item in argv)
    ):
        return None
    return list(argv)


def _baseline_record(value: Report | dict[str, Any] | None) -> dict[str, Any] | None:
    data = _report_data(value)
    if data is None:
        return None
    reproduction = data.get("reproduction") if isinstance(data.get("reproduction"), dict) else {}
    execution = data.get("execution") if isinstance(data.get("execution"), dict) else {}
    return {
        "evidence_id": "baseline-reproduction",
        "report_run_id": _safe_value(data.get("run_id"), 256),
        "outcome": reproduction.get("outcome", "inconclusive"),
        "reason": _safe_value(reproduction.get("reason"), 2_048),
        "stability": _safe_value(reproduction.get("stability"), 128),
        "execution": _public_execution(execution, "baseline-command"),
    }


def _verification_record(
    value: Report | dict[str, Any] | None,
    baseline: dict[str, Any] | None,
    command: dict[str, Any] | None,
    *,
    same_argv: bool | None,
    baseline_run_matches: bool | None,
) -> dict[str, Any]:
    data = _report_data(value)
    verification = (
        data.get("verification") if data and isinstance(data.get("verification"), dict) else {}
    )
    outcome = verification.get("outcome", "not-applicable")
    result: dict[str, Any] = {
        "evidence_id": "verification",
        "outcome": outcome,
        "reason": _safe_value(verification.get("reason"), 2_048),
        "baseline_evidence_id": "baseline-reproduction" if baseline else None,
        "verification_command_evidence_id": "verification-command" if command else None,
        "same_argv": same_argv,
        "same_cwd": verification.get("same_cwd"),
        "same_repository": verification.get("same_repository"),
        "same_remote": verification.get("same_remote"),
        "same_head": verification.get("same_head"),
        "same_timeout": verification.get("same_timeout"),
        "same_termination_policy": verification.get("same_termination_policy"),
        "same_timeout_policy": verification.get("same_timeout_policy"),
        "same_runtime": verification.get("same_runtime"),
        "same_tool": verification.get("same_tool"),
        "identity_complete": verification.get("identity_complete"),
        "baseline_required": True,
    }
    if command:
        result["command"] = command
    if not data:
        result.update(
            {
                "outcome": "not-applicable",
                "reason": "No independent verification report was supplied.",
                "baseline_required": True,
            }
        )
    elif outcome == "verified":
        if not baseline or not command:
            result.update(
                outcome="inconclusive",
                reason="Verified outcome requires baseline and verification command evidence.",
            )
        elif baseline_run_matches is not True:
            result.update(
                outcome="inconclusive",
                reason="Verification baseline run does not match the supplied baseline run.",
            )
        elif (
            baseline.get("outcome") != "reproduced"
            or not isinstance(baseline.get("execution"), dict)
            or baseline["execution"].get("timed_out") is True
            or baseline["execution"].get("exit_code") in {None, 0}
        ):
            result.update(
                outcome="inconclusive",
                reason=(
                    "Verified outcome requires a reproduced baseline with a completed non-zero "
                    "exit code."
                ),
            )
        elif result["same_argv"] is not True:
            result.update(
                outcome="inconclusive",
                reason="Verification argv differs from the baseline argv.",
            )
        elif command.get("timed_out") is True or command.get("exit_code") is None:
            result.update(
                outcome="inconclusive",
                reason="Verification command timeout occurred or no completed exit code exists.",
            )
        elif command.get("exit_code") != 0:
            result.update(
                outcome="inconclusive",
                reason=f"Verification command exited with code {command.get('exit_code')}.",
            )
        elif result.get("identity_complete") is not True or any(
            result.get(key) is not True
            for key in (
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
        ):
            result.update(
                outcome="inconclusive",
                reason="Verified receipt requires complete matching execution identity.",
            )
    return result


def _issue_record(issue: dict[str, Any] | None) -> dict[str, Any]:
    issue = issue if isinstance(issue, dict) else {}
    url = _safe_value(issue.get("url"), 2_048)
    number = issue.get("number")
    if number is None and url:
        match = re.search(r"/issues/(\d+)(?:$|[?#])", url)
        number = int(match.group(1)) if match else None
    source = issue.get("source") or ("github-url" if url else "not-provided")
    return {
        "source": _safe_value(source, 64),
        "url": url,
        "number": number if isinstance(number, int) else None,
        "location": _safe_path_value(issue.get("location"), 2_048),
        "title": _safe_value(issue.get("title"), 512),
        "body_summary_hash": _safe_value(issue.get("body_summary_hash"), 128),
    }


def _repository_record(provenance: GitProvenance | None) -> dict[str, Any]:
    if provenance is None:
        return {
            "root": ".",
            "remote_url": None,
            "head_sha": None,
            "branch": None,
            "dirty": None,
            "identity": None,
            "worktree_path": ".",
            "common_git_dir_sha256": None,
            "start": None,
            "end": None,
            "changed_files": [],
            "changed_files_total": 0,
            "changed_files_recorded": 0,
            "changed_files_truncated": False,
            "changed_files_overflow": False,
            "changed_files_path_overflow": False,
            "changed_files_sha256": None,
            "changed_files_limit": None,
            "changed_file_path_max_bytes": None,
        }
    end = provenance.end.as_dict()
    return {
        "root": provenance.repository_root,
        "remote_url": provenance.remote_url,
        "head_sha": provenance.end.head_sha,
        "branch": provenance.end.branch,
        "dirty": provenance.end.dirty,
        "identity": repository_identity(provenance.repository_root, provenance.remote_url),
        "worktree_path": provenance.worktree_path,
        "common_git_dir_sha256": provenance.common_git_dir_sha256,
        "start": provenance.start.as_dict(),
        "end": end,
        "changed_files": provenance.end.changed_files,
        "changed_files_total": provenance.end.changed_files_total,
        "changed_files_recorded": provenance.end.changed_files_recorded,
        "changed_files_truncated": provenance.end.changed_files_truncated,
        "changed_files_overflow": provenance.end.changed_files_overflow,
        "changed_files_path_overflow": provenance.end.changed_files_path_overflow,
        "changed_files_sha256": provenance.end.changed_files_sha256,
        "changed_files_limit": provenance.end.changed_files_limit,
        "changed_file_path_max_bytes": provenance.end.changed_file_path_max_bytes,
    }


def _evidence_records(
    trace: TraceSummary,
    trace_commands: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    verification: dict[str, Any],
    provenance: GitProvenance | None,
    agents: AgentScan | None,
) -> list[dict[str, Any]]:
    public_command_by_id = {command.get("id"): command for command in trace_commands}
    evidence: list[dict[str, Any]] = [
        {
            "id": "trace",
            "type": "trace",
            "summary": f"Explicit JSONL trace SHA-256 {trace.source_trace_sha256}",
        }
    ]
    for event in trace.events:
        summary = event.summary
        if event.kind == "command":
            public_command = public_command_by_id.get(event.data.get("evidence_id"))
            if public_command:
                summary = (
                    "command execution: "
                    f"{public_command.get('display_command') or '<unknown>'} "
                    f"(exit {public_command.get('exit_code')})"
                )
        evidence.append(
            {
                "id": event.event_id,
                "type": event.kind,
                "line": event.line_number,
                "summary": _safe_value(summary, 4_096),
            }
        )
    for command in trace_commands:
        evidence.append(
            {
                "id": command["id"],
                "type": "command",
                "summary": command.get("display_command") or "command evidence",
                "exit_code": command.get("exit_code"),
            }
        )
    if baseline:
        evidence.append(
            {
                "id": "baseline-reproduction",
                "type": "baseline",
                "summary": baseline.get("reason") or baseline.get("outcome"),
            }
        )
    if verification.get("outcome") != "not-applicable":
        evidence.append(
            {
                "id": "verification",
                "type": "verification",
                "summary": verification.get("reason") or verification.get("outcome"),
            }
        )
    verification_command = verification.get("command")
    if isinstance(verification_command, dict):
        evidence.append(
            {
                "id": verification_command.get("id", "verification-command"),
                "type": "command",
                "summary": verification_command.get("display_command")
                or "verification command evidence",
                "exit_code": verification_command.get("exit_code"),
            }
        )
    if provenance:
        evidence.extend(
            [
                {
                    "id": "git-start",
                    "type": "git-state",
                    "summary": f"start HEAD {provenance.start.head_sha or '<none>'}",
                },
                {
                    "id": "git-end",
                    "type": "git-state",
                    "summary": f"end HEAD {provenance.end.head_sha or '<none>'}",
                },
            ]
        )
    if trace.file_changes:
        evidence.append(
            {
                "id": "trace-files",
                "type": "file-changes",
                "summary": f"{len(trace.file_changes)} trace file change projection(s)",
            }
        )
    if agents:
        for index, item in enumerate(agents.files, start=1):
            evidence.append(
                {
                    "id": f"agents-{index:04d}",
                    "type": "agents-provenance",
                    "summary": item.get("relative_path", "AGENTS file"),
                }
            )
    return evidence


def _verdict(
    verification: dict[str, Any],
    baseline: dict[str, Any] | None,
    claims: list[Claim],
    trace: TraceSummary,
) -> str:
    if trace.parse_errors or trace.event_limit_reached or trace.valid_events == 0:
        return "inconclusive"
    if verification.get("outcome") == "not-fixed":
        return "refuted"
    if any(claim.status == "refuted" for claim in claims):
        return "refuted"
    if verification.get("outcome") == "inconclusive":
        return "inconclusive"
    if verification.get("outcome") == "verified":
        if any(claim.status == "unverified" for claim in claims):
            return "partially-verified"
        return "verified"
    if baseline and baseline.get("outcome") == "reproduced":
        return "unverified"
    if claims and any(claim.status == "supported" for claim in claims):
        return "partially-verified"
    return "unverified"


def _report_dict(value: Report | dict[str, Any]) -> dict[str, Any]:
    return value.as_dict() if isinstance(value, Report) else dict(value)


def _report_execution(value: Report | dict[str, Any]) -> dict[str, Any]:
    execution = _report_dict(value).get("execution")
    return execution if isinstance(execution, dict) else {}


def _report_repository(value: Report | dict[str, Any]) -> dict[str, Any]:
    repository = _report_dict(value).get("repository")
    return repository if isinstance(repository, dict) else {}


_IDENTITY_COMPARISONS = (
    ("same_argv", "argv_identity"),
    ("same_cwd", "cwd_identity"),
    ("same_repository", "repository_identity"),
    ("same_remote", "remote_url"),
    ("same_head", "head_sha"),
    ("same_timeout", "timeout_seconds"),
    ("same_termination_policy", "termination_policy"),
    ("same_timeout_policy", "timeout_policy_identity"),
    ("same_runtime", "runtime_identity"),
    ("same_tool", "tool_identity"),
)


def _identity_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value or REDACTION in value:
        return None
    return value


def _report_identity(value: Report | dict[str, Any]) -> dict[str, Any]:
    """Recompute identity inputs from report fields, never from stored same_* values."""

    data = _report_dict(value)
    execution = _report_execution(value)
    repository = _report_repository(value)
    argv = _exact_argv(execution)
    cwd = _identity_text(execution.get("cwd"))
    root = _identity_text(repository.get("root"))
    remote = _identity_text(repository.get("remote_url"))
    head = _identity_text(repository.get("head_sha"))
    runtime = data.get("runtime")
    runtime_is_complete = (
        isinstance(runtime, dict)
        and isinstance(runtime.get("os"), str)
        and bool(runtime.get("os"))
        and isinstance(runtime.get("architecture"), str)
        and bool(runtime.get("architecture"))
        and isinstance(runtime.get("versions"), dict)
        and bool(runtime.get("versions"))
    )
    return {
        "argv_identity": argv_identity(argv) if argv else None,
        "cwd_identity": cwd_identity(cwd) if cwd else None,
        "repository_identity": repository_identity(root, remote) if root else None,
        "remote_url": remote,
        "head_sha": head,
        "timeout_seconds": execution.get("timeout_seconds"),
        "termination_policy": _identity_text(execution.get("termination_policy")),
        "timeout_policy_identity": timeout_policy_identity(
            execution.get("timeout_seconds"),
            execution.get("termination_policy"),
            execution.get("capture_limits"),
        ),
        "runtime_identity": runtime_identity(runtime) if runtime_is_complete else None,
        "tool_identity": tool_identity(data.get("tool_version")),
    }


def _compare_report_identities(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, bool | None]:
    result: dict[str, bool | None] = {}
    for same_key, value_key in _IDENTITY_COMPARISONS:
        left = baseline.get(value_key)
        right = current.get(value_key)
        result[same_key] = None if left is None or right is None else left == right
    result["identity_complete"] = all(result[key] is not None for key, _ in _IDENTITY_COMPARISONS)
    return result


def _report_json_hash(value: Report | dict[str, Any]) -> str:
    data = _report_dict(value)
    return sha256_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _effective_report_hashes(
    baselines: list[Report | dict[str, Any]],
    verification: Report | dict[str, Any],
    check_reports: list[Report | dict[str, Any]],
    supplied: dict[str, Any] | None,
) -> dict[str, Any]:
    supplied = supplied or {}
    baseline_hashes = list(supplied.get("baselines", []))
    if not baseline_hashes:
        baseline_hashes = [_report_json_hash(report) for report in baselines]
    verification_hash = supplied.get("verification") or _report_json_hash(verification)
    check_hashes = list(supplied.get("checks", []))
    if not check_hashes:
        check_hashes = [_report_json_hash(report) for report in check_reports]
    return {
        "baselines": baseline_hashes,
        "verification": verification_hash,
        "checks": check_hashes,
    }


def _baseline_group(
    baselines: list[Report | dict[str, Any]],
    *,
    report_hashes: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    hashes = report_hashes or []
    for index, baseline in enumerate(baselines):
        data = _report_dict(baseline)
        execution = _report_execution(baseline)
        identity = _report_identity(baseline)
        records.append(
            {
                "run_id": _safe_value(data.get("run_id"), 256),
                "report_sha256": hashes[index] if index < len(hashes) else None,
                "outcome": (
                    data.get("reproduction", {}).get("outcome")
                    if isinstance(data.get("reproduction"), dict)
                    else "inconclusive"
                ),
                "stability": (
                    data.get("reproduction", {}).get("stability")
                    if isinstance(data.get("reproduction"), dict)
                    else "unknown"
                ),
                **identity,
                "exit_code": execution.get("exit_code"),
                "timed_out": bool(execution.get("timed_out", False)),
                "identity_complete": all(
                    identity.get(value_key) is not None for _, value_key in _IDENTITY_COMPARISONS
                ),
            }
        )
    comparisons: dict[str, bool | None] = {}
    for same_key, value_key in _IDENTITY_COMPARISONS:
        values = [record.get(value_key) for record in records]
        comparisons[same_key] = (
            None
            if not values or any(value is None for value in values)
            else all(value == values[0] for value in values)
        )
    completed_nonzero = all(
        record.get("outcome") == "reproduced"
        and record.get("exit_code") not in {None, 0}
        and record.get("timed_out") is False
        for record in records
    )
    identity_complete = bool(records) and all(
        comparisons[key] is not None for key, _ in _IDENTITY_COMPARISONS
    )
    if len(records) < 2:
        stability = "single-run"
    elif identity_complete and completed_nonzero:
        stability = "stable"
    else:
        stability = "unstable"
    group_id = sha256_text(
        json.dumps(
            {
                "runs": records,
                "stability": stability,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    group = {
        "group_id": group_id,
        "required_runs": 2,
        "run_count": len(records),
        "run_ids": [record.get("run_id") for record in records],
        "reports": records,
        "stability_rule": (
            "at least two completed non-zero, non-timeout runs with identical argv, cwd, "
            "repository, remote, HEAD, timeout, termination, runtime and tool identities"
        ),
        "stability": stability,
        "identity_complete": identity_complete,
        "completed_nonzero": completed_nonzero,
        **comparisons,
    }
    return group, records


def _report_verification_record(
    verification: Report | dict[str, Any],
    baseline_group: dict[str, Any],
    baselines: list[Report | dict[str, Any]],
    identity_mode: str,
    report_hashes: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    data = _report_dict(verification)
    verification_data = data.get("verification")
    verification_data = verification_data if isinstance(verification_data, dict) else {}
    execution = _report_execution(verification)
    command = _public_execution(execution, "verification-command")
    baseline_run_id = verification_data.get("baseline_run_id")
    baseline_index = next(
        (
            index
            for index, baseline in enumerate(baselines)
            if _report_dict(baseline).get("run_id") == baseline_run_id
        ),
        None,
    )
    selected_baseline = baselines[baseline_index] if baseline_index is not None else None
    report_modes = [
        _report_repository(report).get("identity_mode", "local") for report in baselines
    ]
    report_modes.append(_report_repository(verification).get("identity_mode", "local"))
    identity_mode_match = bool(report_modes) and all(mode == identity_mode for mode in report_modes)
    recomputed = (
        _compare_report_identities(
            _report_identity(selected_baseline),
            _report_identity(verification),
        )
        if selected_baseline is not None
        else {key: None for key, _ in _IDENTITY_COMPARISONS} | {"identity_complete": False}
    )
    baseline_hashes = list((report_hashes or {}).get("baselines", []))
    actual_baseline_hash = (
        baseline_hashes[baseline_index]
        if baseline_index is not None and baseline_index < len(baseline_hashes)
        else None
    )
    recorded_baseline_hash = verification_data.get("baseline_report_sha256")
    baseline_hash_match = (
        actual_baseline_hash == recorded_baseline_hash
        if actual_baseline_hash is not None and isinstance(recorded_baseline_hash, str)
        else None
    )
    result: dict[str, Any] = {
        "evidence_id": "verification",
        "outcome": verification_data.get("outcome", "inconclusive"),
        "reason": _safe_value(verification_data.get("reason"), 2_048),
        "baseline_evidence_id": "baseline-reproduction",
        "baseline_group_id": baseline_group.get("group_id"),
        "baseline_run_id": baseline_run_id,
        "verification_command_evidence_id": "verification-command" if command else None,
        **recomputed,
        "baseline_required": True,
        "identity_mode": identity_mode,
        "identity_mode_match": identity_mode_match,
        "baseline_report_sha256": recorded_baseline_hash,
        "baseline_report_hash_match": baseline_hash_match,
        "baseline_report_hashes": baseline_hashes,
        "verification_report_sha256": (report_hashes or {}).get("verification"),
    }
    if command:
        result["command"] = command
    if result["outcome"] == "verified":
        if baseline_group.get("stability") != "stable":
            result.update(
                outcome="inconclusive",
                reason="Verified receipt requires a stable baseline group of at least two runs.",
            )
        elif result.get("identity_mode_match") is not True:
            result.update(
                outcome="inconclusive",
                reason="Receipt identity mode does not match every supplied core report.",
            )
        elif result.get("baseline_run_id") not in baseline_group.get("run_ids", []):
            result.update(
                outcome="inconclusive",
                reason=("Verification baseline run is not present in the supplied baseline group."),
            )
        elif result.get("baseline_report_hash_match") is not True:
            result.update(
                outcome="inconclusive",
                reason=(
                    "Verification report does not identify the exact baseline report supplied "
                    "to the receipt."
                ),
            )
        elif result.get("identity_complete") is not True or any(
            result.get(key) is not True
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
        ):
            result.update(
                outcome="inconclusive",
                reason="Verified receipt requires complete matching execution identity.",
            )
        elif not command or command.get("timed_out") or command.get("exit_code") != 0:
            result.update(
                outcome="inconclusive",
                reason="Verified receipt requires a completed verification command with exit 0.",
            )
    return result, command


def _report_evidence_records(
    baseline_group: dict[str, Any],
    baseline: dict[str, Any] | None,
    verification: dict[str, Any],
    verification_command: dict[str, Any] | None,
    provenance: GitProvenance | None,
    agents: AgentScan | None,
    checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence = [
        {
            "id": "baseline-group",
            "type": "baseline-group",
            "summary": f"{baseline_group.get('run_count', 0)} baseline run(s), "
            f"stability {baseline_group.get('stability')}",
        }
    ]
    if baseline:
        evidence.append(
            {
                "id": "baseline-reproduction",
                "type": "baseline",
                "summary": baseline.get("reason") or baseline.get("outcome"),
            }
        )
    evidence.append(
        {
            "id": "verification",
            "type": "verification",
            "summary": verification.get("reason") or verification.get("outcome"),
        }
    )
    if verification_command:
        evidence.append(
            {
                "id": "verification-command",
                "type": "command",
                "summary": verification_command.get("display_command")
                or verification_command.get("argv"),
                "exit_code": verification_command.get("exit_code"),
            }
        )
    evidence.extend(
        {
            "id": item["id"],
            "type": "check",
            "summary": item.get("summary") or item.get("outcome") or "check report",
        }
        for item in checks
    )
    if provenance:
        evidence.extend(
            [
                {
                    "id": "git-start",
                    "type": "git-state",
                    "summary": f"start HEAD {provenance.start.head_sha or '<none>'}",
                },
                {
                    "id": "git-end",
                    "type": "git-state",
                    "summary": f"end HEAD {provenance.end.head_sha or '<none>'}",
                },
            ]
        )
    if agents:
        evidence.extend(
            {
                "id": f"agents-{index:04d}",
                "type": "agents-provenance",
                "summary": item.get("relative_path", "AGENTS file"),
            }
            for index, item in enumerate(agents.files, start=1)
        )
    return evidence


def _check_records(
    check_reports: list[Report | dict[str, Any]],
    *,
    report_hashes: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    def classify_check(
        report: dict[str, Any], execution: dict[str, Any], verification: dict[str, Any]
    ) -> tuple[str, str]:
        completed = not bool(execution.get("timed_out", False)) and isinstance(
            execution.get("exit_code"), int
        )
        verification_outcome = verification.get("outcome")
        if verification_outcome == "verified":
            if completed and execution.get("exit_code") == 0:
                return "passed", "The independent check completed with exit code 0."
            return "inconclusive", (
                "The check claimed verification but its execution was incomplete."
            )
        if verification_outcome in {"not-fixed", "refuted"}:
            return "failed", "The check reported a failing verification outcome."
        if verification_outcome == "inconclusive":
            return "inconclusive", "The check reported inconclusive evidence."

        reproduction = report.get("reproduction")
        reproduction_outcome = (
            reproduction.get("outcome") if isinstance(reproduction, dict) else None
        )
        if not completed:
            return "inconclusive", "The collection check timed out or has no completed exit code."
        if reproduction_outcome == "not-reproduced" and execution.get("exit_code") == 0:
            return "passed", (
                "The collection check command completed with exit code 0; "
                "not-reproduced is not itself a check status."
            )
        if reproduction_outcome == "reproduced" and execution.get("exit_code") != 0:
            return "failed", "The collection check command exited non-zero."
        return "inconclusive", "The collection report does not contain a decisive check outcome."

    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, report in enumerate(check_reports, start=1):
        data = _report_dict(report)
        execution = _report_execution(report)
        verification = data.get("verification")
        verification = verification if isinstance(verification, dict) else {}
        source_outcome = verification.get("outcome")
        outcome, outcome_reason = classify_check(data, execution, verification)
        runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
        check_hashes = list((report_hashes or {}).get("checks", []))
        command = _public_execution(execution, f"check-{index:04d}") or {
            "id": f"check-{index:04d}",
            "argv": [],
            "exit_code": None,
            "timed_out": False,
        }
        command["id"] = f"check-{index:04d}"
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        check = {
            **command,
            "purpose": "additional-regression-check",
            "outcome": outcome,
            "status": outcome,
            "source_outcome": source_outcome,
            "report_run_id": data.get("run_id"),
            "report_sha256": check_hashes[index - 1] if index <= len(check_hashes) else None,
            "runtime_identity": runtime_identity(runtime) if runtime else None,
            "summary": outcome_reason
            or verification.get("reason")
            or (notes[0] if notes else "check report"),
        }
        checks.append(check)
        if outcome != "passed":
            warnings.append(f"{check['id']} did not pass: {outcome}")
    return checks, warnings


def _report_verdict(
    verification: dict[str, Any],
    baseline_group: dict[str, Any],
    claims: list[Claim],
    trace_status: str = "absent",
    checks: list[dict[str, Any]] | None = None,
) -> str:
    effective_claims = claims
    if trace_status in {"absent", "invalid", "truncated"}:
        effective_claims = [
            claim
            for claim in claims
            if not (
                claim.source == "final-message-heuristic"
                or claim.evidence_ids
                and all(
                    evidence_id == "trace"
                    or evidence_id == "trace-files"
                    or evidence_id.startswith("event-")
                    for evidence_id in claim.evidence_ids
                )
            )
        ]
    if verification.get("outcome") in {"not-fixed", "refuted"}:
        return "refuted"
    if verification.get("outcome") == "inconclusive":
        return "inconclusive"
    if verification.get("outcome") == "verified":
        if any(claim.status == "refuted" for claim in effective_claims):
            return "refuted"
        if any(
            check.get("outcome") != "passed" or check.get("exit_code") != 0
            for check in checks or []
        ):
            return "partially-verified"
        if any(claim.status == "unverified" for claim in effective_claims):
            return "partially-verified"
        return "verified" if baseline_group.get("stability") == "stable" else "inconclusive"
    return "unverified"


def build_report_receipt(
    baselines: list[Report | dict[str, Any]],
    verification: Report | dict[str, Any],
    *,
    repo_root: Path,
    issue: dict[str, Any] | None = None,
    trace: TraceSummary | None = None,
    agents: AgentScan | None = None,
    claim_inputs: Iterable[Claim | dict[str, Any]] = (),
    check_reports: list[Report | dict[str, Any]] | None = None,
    report_hashes: dict[str, Any] | None = None,
    identity_mode: str = "github",
    include_heuristics: bool = False,
    generated_at: str | None = None,
) -> CodexMaintenanceReceipt:
    """Build a receipt from core reports, optionally enriched by a Codex trace."""

    if not baselines:
        raise SchemaValidationError("at least one baseline report is required")
    if identity_mode not in {"github", "local"}:
        raise SchemaValidationError("identity_mode must be github or local")
    check_reports = list(check_reports or [])
    effective_hashes = _effective_report_hashes(
        baselines,
        verification,
        check_reports,
        report_hashes,
    )
    baseline_group, _ = _baseline_group(
        baselines,
        report_hashes=list(effective_hashes["baselines"]),
    )
    provenance_warnings: list[str] = []
    try:
        provenance = collect_git_provenance(repo_root)
        provenance_warnings.extend(provenance.warnings)
    except (OSError, ValueError) as exc:
        provenance = None
        provenance_warnings.append(f"Git provenance unavailable: {exc.__class__.__name__}")
    baseline_record = _baseline_record(_report_dict(baselines[0]))
    verification_record, verification_command = _report_verification_record(
        verification,
        baseline_group,
        baselines,
        identity_mode,
        effective_hashes,
    )
    checks, check_warnings = _check_records(
        check_reports,
        report_hashes=effective_hashes,
    )
    commands = [verification_command] if verification_command else []
    commands.extend(checks)
    trace_files = trace.file_changes if trace else []
    trace_warnings = list(trace.warnings) if trace else []
    trace_redactions = list(trace.redactions) if trace else []
    trace_unknown_events = list(trace.unknown_event_types) if trace else []
    trace_parse_errors = list(trace.parse_errors) if trace else []
    if trace is None:
        trace_status = "absent"
    elif trace.event_limit_reached:
        trace_status = "truncated"
    elif trace.parse_errors or trace.valid_events == 0:
        trace_status = "invalid"
    else:
        trace_status = "present"
    warnings = list(
        dict.fromkeys(
            provenance_warnings
            + check_warnings
            + (
                [
                    "local identity mode selected; missing remote or HEAD keeps the "
                    "core receipt inconclusive"
                ]
                if identity_mode == "local"
                and any(
                    not _report_repository(report).get("remote_url")
                    or not _report_repository(report).get("head_sha")
                    for report in [*baselines, verification]
                )
                else []
            )
            + (
                [
                    "GitHub identity mode requires a non-empty remote URL and HEAD in "
                    "every core report"
                ]
                if identity_mode == "github"
                and any(
                    not _report_repository(report).get("remote_url")
                    or not _report_repository(report).get("head_sha")
                    for report in [*baselines, verification]
                )
                else []
            )
            + trace_warnings
            + (
                [f"trace-{trace_status}: trace-specific activity claims are unavailable"]
                if trace_status in {"invalid", "truncated"}
                else []
            )
            + (
                ["trace-not-supplied: Codex activity provenance was not provided"]
                if trace is None
                else []
            )
        )
    )
    if agents:
        warnings.extend(agents.warnings)
    warnings = list(dict.fromkeys(warnings))
    claim_evidence = {
        "commands": commands,
        "baseline": baseline_record,
        "verification": verification_record,
        "git": provenance.as_dict() if provenance else {},
        "trace_files": trace_files,
        "final_messages": trace.final_messages if trace else [],
        "evidence_ids": [
            item["id"]
            for item in _report_evidence_records(
                baseline_group,
                baseline_record,
                verification_record,
                verification_command,
                provenance,
                agents,
                checks,
            )
        ],
    }
    claim_items = list(claim_inputs)
    claims, claim_warnings = verify_claims(
        claim_items,
        claim_evidence,
        include_heuristics=include_heuristics and trace is not None,
    )
    if not claim_items:
        default_claims: list[Claim] = []
        if baseline_record:
            default_claims.append(
                Claim(
                    id="default-bug-reproduced",
                    type="bug-reproduced",
                    evidence_ids=["baseline-reproduction"],
                )
            )
        if verification_record.get("outcome") != "not-applicable":
            default_claims.append(
                Claim(
                    id="default-fix-verified",
                    type="fix-verified",
                    evidence_ids=["verification"],
                )
            )
        claims, default_warnings = verify_claims(default_claims, claim_evidence)
        claim_warnings.extend(default_warnings)
    warnings.extend(claim_warnings)
    warnings = list(dict.fromkeys(warnings))
    evidence = _report_evidence_records(
        baseline_group,
        baseline_record,
        verification_record,
        verification_command,
        provenance,
        agents,
        checks,
    )
    if trace:
        evidence = _evidence_records(
            trace,
            commands,
            baseline_record,
            verification_record,
            provenance,
            agents,
        )
        evidence.append(
            {
                "id": "baseline-group",
                "type": "baseline-group",
                "summary": f"{baseline_group['run_count']} baseline run(s), stability "
                f"{baseline_group['stability']}",
            }
        )
    receipt = CodexMaintenanceReceipt(
        receipt_schema_version=RECEIPT_SCHEMA_VERSION,
        receipt_type=RECEIPT_TYPE,
        tool_version=__version__,
        generated_at=generated_at or _utc_now(),
        codex=(
            {
                "cli_version": trace.codex_cli_version,
                "app_version": trace.codex_app_version,
                "task_id": trace.task_id,
                "session_id": trace.session_id,
                "source_trace_sha256": trace.source_trace_sha256,
                "adapter": trace.adapter_status,
                "raw_trace_persisted": False,
                "messages_included": trace.include_messages,
            }
            if trace
            else None
        ),
        identity_mode=identity_mode,
        repository=_repository_record(provenance),
        issue=_issue_record(issue),
        baseline=baseline_record,
        commands=commands,
        verification=verification_record,
        agents=agents.as_dict()
        if agents
        else {
            "scope_model": "not-collected",
            "files": [],
            "warnings": [],
            "include_content": False,
        },
        trace=(
            {
                "status": trace_status,
                "name": trace.trace_name,
                "sha256": trace.source_trace_sha256,
                "lines_seen": trace.lines_seen,
                "valid_events": trace.valid_events,
                "unknown_event_count": trace.unknown_events,
                "event_limit_reached": trace.event_limit_reached,
                "include_messages": trace.include_messages,
            }
            if trace
            else {
                "status": "absent",
                "name": None,
                "sha256": None,
                "lines_seen": 0,
                "valid_events": 0,
                "unknown_event_count": 0,
                "event_limit_reached": False,
                "include_messages": False,
            }
        ),
        evidence=evidence,
        claims=[claim.as_dict() for claim in claims],
        verdict=_report_verdict(
            verification_record,
            baseline_group,
            claims,
            trace_status,
            checks,
        ),
        warnings=warnings,
        redactions=trace_redactions,
        unknown_events=trace_unknown_events,
        parse_errors=trace_parse_errors,
        receipt_mode="core-and-trace" if trace else "core-verification",
        trace_status=trace_status,
        baseline_group=baseline_group,
        checks=checks,
        report_hashes=effective_hashes,
    )
    validate_receipt_dict(receipt.as_dict())
    return receipt


@dataclass
class CodexMaintenanceReceipt:
    """Portable, redacted evidence object for one Codex-assisted maintenance run."""

    receipt_schema_version: str
    receipt_type: str
    tool_version: str
    generated_at: str
    codex: dict[str, Any] | None
    repository: dict[str, Any]
    issue: dict[str, Any]
    baseline: dict[str, Any] | None
    commands: list[dict[str, Any]]
    verification: dict[str, Any]
    agents: dict[str, Any]
    trace: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    verdict: str
    warnings: list[str] = None  # type: ignore[assignment]
    redactions: list[str] = None  # type: ignore[assignment]
    unknown_events: list[str] = None  # type: ignore[assignment]
    parse_errors: list[dict[str, Any]] = None  # type: ignore[assignment]
    receipt_mode: str = "trace-oriented"
    trace_status: str = "present"
    identity_mode: str = "local"
    baseline_group: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = None  # type: ignore[assignment]
    report_hashes: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.warnings = list(self.warnings or [])
        self.redactions = list(self.redactions or [])
        self.unknown_events = list(self.unknown_events or [])
        self.parse_errors = list(self.parse_errors or [])
        self.checks = list(self.checks or [])
        self.report_hashes = dict(self.report_hashes or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_schema_version": self.receipt_schema_version,
            "receipt_type": self.receipt_type,
            "tool_version": self.tool_version,
            "generated_at": self.generated_at,
            "codex": self.codex,
            "repository": self.repository,
            "issue": self.issue,
            "baseline": self.baseline,
            "commands": self.commands,
            "verification": self.verification,
            "agents": self.agents,
            "trace": self.trace,
            "evidence": self.evidence,
            "claims": self.claims,
            "verdict": self.verdict,
            "warnings": self.warnings,
            "redactions": self.redactions,
            "unknown_events": self.unknown_events,
            "parse_errors": self.parse_errors,
            "receipt_mode": self.receipt_mode,
            "trace_status": self.trace_status,
            "identity_mode": self.identity_mode,
            "baseline_group": self.baseline_group,
            "checks": self.checks,
            "report_hashes": self.report_hashes,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n"


def build_receipt(
    trace: TraceSummary,
    *,
    repo_root: Path | None = None,
    issue: dict[str, Any] | None = None,
    baseline: Report | dict[str, Any] | None = None,
    verification: Report | dict[str, Any] | None = None,
    verification_command: dict[str, Any] | None = None,
    agents: AgentScan | None = None,
    claim_inputs: Iterable[Claim | dict[str, Any]] = (),
    include_heuristics: bool = False,
    generated_at: str | None = None,
) -> CodexMaintenanceReceipt:
    claim_items = list(claim_inputs)
    provenance: GitProvenance | None = None
    provenance_warnings: list[str] = []
    if repo_root is not None:
        try:
            provenance = collect_git_provenance(repo_root)
            provenance_warnings.extend(provenance.warnings)
        except (OSError, ValueError) as exc:
            provenance_warnings.append(f"Git provenance unavailable: {exc.__class__.__name__}")

    baseline_data = _report_data(baseline)
    verification_data = _report_data(verification)
    baseline_execution = baseline_data.get("execution") if baseline_data else None
    baseline_argv = _exact_argv(baseline_execution)
    verification_argv = _exact_argv(verification_command)
    same_argv = (
        baseline_argv == verification_argv
        if baseline_argv is not None and verification_argv is not None
        else None
    )
    baseline_run_id = baseline_data.get("run_id") if baseline_data else None
    verification_details = (
        verification_data.get("verification")
        if verification_data and isinstance(verification_data.get("verification"), dict)
        else {}
    )
    verification_baseline_run_id = verification_details.get("baseline_run_id")
    baseline_run_matches = (
        baseline_run_id == verification_baseline_run_id
        if isinstance(baseline_run_id, str)
        and baseline_run_id
        and isinstance(verification_baseline_run_id, str)
        and verification_baseline_run_id
        else None
    )
    baseline_record = _baseline_record(baseline_data)
    public_verification_command = (
        _public_execution(verification_command, "verification-command")
        if verification_command
        else None
    )
    if public_verification_command:
        public_verification_command["id"] = "verification-command"
    verification_record = _verification_record(
        verification_data,
        baseline_record,
        public_verification_command,
        same_argv=same_argv,
        baseline_run_matches=baseline_run_matches,
    )
    commands = [
        projected
        for command in trace.command_evidence
        if (projected := _public_execution(command, str(command.get("id") or "trace-command")))
    ]
    if public_verification_command:
        commands.append(public_verification_command)
    claim_evidence = {
        "commands": commands,
        "baseline": baseline_record,
        "verification": verification_record,
        "git": provenance.as_dict() if provenance else {},
        "trace_files": trace.file_changes,
        "final_messages": trace.final_messages,
        "evidence_ids": [
            item["id"]
            for item in _evidence_records(
                trace, commands, baseline_record, verification_record, provenance, agents
            )
        ],
    }
    claims, claim_warnings = verify_claims(
        claim_items,
        claim_evidence,
        include_heuristics=include_heuristics,
    )
    if not claim_items and baseline_record:
        default_claim = Claim(
            id="default-bug-reproduced",
            type="bug-reproduced",
            evidence_ids=["baseline-reproduction"],
        )
        claims, default_warnings = verify_claims([default_claim], claim_evidence)
        claim_warnings.extend(default_warnings)
    if not claim_items and verification_record.get("outcome") != "not-applicable":
        default_claim = Claim(
            id="default-fix-verified",
            type="fix-verified",
            evidence_ids=["verification"],
        )
        extra_claims, default_warnings = verify_claims([default_claim], claim_evidence)
        claims.extend(extra_claims)
        claim_warnings.extend(default_warnings)
    warnings = list(dict.fromkeys(trace.warnings + provenance_warnings + claim_warnings))
    if agents:
        warnings.extend(agents.warnings)
    warnings = list(dict.fromkeys(warnings))
    redactions = list(dict.fromkeys(trace.redactions))
    if not trace.include_messages:
        warnings.append("raw conversation and assistant reasoning were not persisted")
    if trace.adapter_status.startswith("experimental"):
        warnings.append(
            "Codex event adapter is experimental-compatible; verify public fields before "
            "relying on them"
        )
    receipt = CodexMaintenanceReceipt(
        receipt_schema_version=RECEIPT_SCHEMA_VERSION,
        receipt_type=RECEIPT_TYPE,
        tool_version=__version__,
        generated_at=generated_at or _utc_now(),
        codex={
            "cli_version": trace.codex_cli_version,
            "app_version": trace.codex_app_version,
            "task_id": trace.task_id,
            "session_id": trace.session_id,
            "source_trace_sha256": trace.source_trace_sha256,
            "adapter": trace.adapter_status,
            "raw_trace_persisted": False,
            "messages_included": trace.include_messages,
        },
        repository=_repository_record(provenance),
        issue=_issue_record(issue),
        baseline=baseline_record,
        commands=commands,
        verification=verification_record,
        agents=agents.as_dict()
        if agents
        else {
            "scope_model": "not-collected",
            "files": [],
            "warnings": [],
            "include_content": False,
        },
        trace={
            "status": "present",
            "name": trace.trace_name,
            "sha256": trace.source_trace_sha256,
            "lines_seen": trace.lines_seen,
            "valid_events": trace.valid_events,
            "unknown_event_count": trace.unknown_events,
            "event_limit_reached": trace.event_limit_reached,
            "include_messages": trace.include_messages,
        },
        evidence=_evidence_records(
            trace, commands, baseline_record, verification_record, provenance, agents
        ),
        claims=[claim.as_dict() for claim in claims],
        verdict=_verdict(verification_record, baseline_record, claims, trace),
        warnings=warnings,
        redactions=redactions,
        unknown_events=trace.unknown_event_types,
        parse_errors=trace.parse_errors,
    )
    validate_receipt_dict(receipt.as_dict())
    return receipt


def validate_receipt_dict(data: dict[str, Any]) -> None:
    errors: list[str] = []
    required = {
        "receipt_schema_version",
        "receipt_type",
        "tool_version",
        "generated_at",
        "codex",
        "repository",
        "issue",
        "baseline",
        "commands",
        "verification",
        "agents",
        "trace",
        "evidence",
        "claims",
        "verdict",
        "warnings",
        "redactions",
        "unknown_events",
        "parse_errors",
        "receipt_mode",
        "trace_status",
        "identity_mode",
        "baseline_group",
        "checks",
        "report_hashes",
    }
    if data.get("receipt_schema_version") == "1.0.0":
        required -= {
            "receipt_mode",
            "trace_status",
            "identity_mode",
            "baseline_group",
            "checks",
            "report_hashes",
        }
    errors.extend(f"missing required field: {key}" for key in sorted(required - set(data)))
    errors.extend(f"unexpected field: {key}" for key in sorted(set(data) - required))
    if data.get("receipt_schema_version") not in SUPPORTED_RECEIPT_SCHEMA_VERSIONS:
        errors.append(
            "receipt_schema_version must be one of "
            + ", ".join(sorted(SUPPORTED_RECEIPT_SCHEMA_VERSIONS))
        )
    if data.get("receipt_type") != RECEIPT_TYPE:
        errors.append(f"receipt_type must be {RECEIPT_TYPE}")
    if not isinstance(data.get("tool_version"), str) or not data.get("tool_version"):
        errors.append("tool_version must be a non-empty string")
    generated_at = data.get("generated_at")
    if not isinstance(generated_at, str):
        errors.append("generated_at must be an RFC 3339 date-time string")
    else:
        try:
            parsed_generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("generated_at must be an RFC 3339 date-time string")
        else:
            if parsed_generated_at.tzinfo is None:
                errors.append("generated_at must include a UTC offset")
    if data.get("verdict") not in RECEIPT_VERDICTS:
        errors.append("verdict has an unsupported value")
    if data.get("receipt_schema_version") != "1.0.0" and data.get("identity_mode") not in {
        "github",
        "local",
    }:
        errors.append("identity_mode has an unsupported value")
    repository = data.get("repository")
    if isinstance(repository, dict):
        for key in (
            "changed_files_total",
            "changed_files_recorded",
            "changed_files_limit",
            "changed_file_path_max_bytes",
        ):
            value = repository.get(key)
            if value is not None and (not isinstance(value, int) or value < 0):
                errors.append(f"repository.{key} must be a non-negative integer when supplied")
        for key in (
            "changed_files_truncated",
            "changed_files_overflow",
            "changed_files_path_overflow",
        ):
            value = repository.get(key)
            if value is not None and not isinstance(value, bool):
                errors.append(f"repository.{key} must be a boolean when supplied")
        digest = repository.get("changed_files_sha256")
        if digest is not None and (not isinstance(digest, str) or not HASH_RE.fullmatch(digest)):
            errors.append("repository.changed_files_sha256 must be a lowercase SHA-256 hash")
    else:
        errors.append("repository must be an object")
    trace = data.get("trace")
    if not isinstance(trace, dict):
        errors.append("trace must be an object")
    if isinstance(trace, dict):
        status = trace.get("status", "present")
        if status not in {"absent", "present", "invalid", "truncated"}:
            errors.append("trace.status has an unsupported value")
        if status == "absent":
            if trace.get("sha256") is not None:
                errors.append("trace.sha256 must be null when trace was not supplied")
        elif not isinstance(trace.get("sha256"), str) or not HASH_RE.fullmatch(
            trace.get("sha256", "")
        ):
            errors.append("trace.sha256 must be a lowercase SHA-256 hash when trace is supplied")
        for key in ("lines_seen", "valid_events", "unknown_event_count"):
            value = trace.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"trace.{key} must be a non-negative integer")
        for key in ("include_messages", "event_limit_reached"):
            if key in trace and not isinstance(trace[key], bool):
                errors.append(f"trace.{key} must be boolean")
    codex = data.get("codex")
    if codex is not None and (
        not isinstance(codex, dict)
        or not isinstance(codex.get("source_trace_sha256"), str)
        or not HASH_RE.fullmatch(codex.get("source_trace_sha256", ""))
    ):
        errors.append(
            "codex.source_trace_sha256 must be a lowercase SHA-256 hash when codex is present"
        )
    if isinstance(codex, dict):
        required_codex = {
            "cli_version",
            "app_version",
            "task_id",
            "session_id",
            "source_trace_sha256",
            "adapter",
            "raw_trace_persisted",
            "messages_included",
        }
        errors.extend(
            f"missing required field: codex.{key}" for key in sorted(required_codex - set(codex))
        )
        errors.extend(
            f"unexpected field: codex.{key}" for key in sorted(set(codex) - required_codex)
        )
        if codex.get("raw_trace_persisted") is not False:
            errors.append("codex.raw_trace_persisted must be false")
        if not isinstance(codex.get("messages_included"), bool):
            errors.append("codex.messages_included must be boolean")
    verification = data.get("verification")
    if isinstance(verification, dict):
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
            "identity_complete",
            "baseline_report_hash_match",
            "identity_mode_match",
        ):
            if key in verification and not isinstance(verification[key], (bool, type(None))):
                errors.append(f"verification.{key} must be boolean or null")
        for key in ("baseline_report_sha256", "verification_report_sha256"):
            value = verification.get(key)
            if value is not None and (not isinstance(value, str) or not HASH_RE.fullmatch(value)):
                errors.append(f"verification.{key} must be a SHA-256 hash or null")
    for key in ("issue", "verification", "agents"):
        if not isinstance(data.get(key), dict):
            errors.append(f"{key} must be an object")
    if data.get("baseline") is not None and not isinstance(data.get("baseline"), dict):
        errors.append("baseline must be an object or null")
    for key in ("commands", "evidence", "claims"):
        if not isinstance(data.get(key), list):
            errors.append(f"{key} must be an array")
        elif not all(isinstance(item, dict) for item in data[key]):
            errors.append(f"{key} items must be objects")
    for key in ("warnings", "redactions", "unknown_events"):
        if not isinstance(data.get(key), list):
            errors.append(f"{key} must be an array")
        elif not all(isinstance(item, str) for item in data[key]):
            errors.append(f"{key} items must be strings")
    if not isinstance(data.get("parse_errors"), list):
        errors.append("parse_errors must be an array")
    elif not all(isinstance(item, dict) for item in data["parse_errors"]):
        errors.append("parse_errors items must be objects")
    if data.get("receipt_schema_version") != "1.0.0":
        if data.get("receipt_mode") not in {
            "trace-oriented",
            "core-verification",
            "core-and-trace",
        }:
            errors.append("receipt_mode has an unsupported value")
        if data.get("trace_status") not in {"absent", "present", "invalid", "truncated"}:
            errors.append("trace_status has an unsupported value")
        if data.get("baseline_group") is not None and not isinstance(
            data.get("baseline_group"), dict
        ):
            errors.append("baseline_group must be an object or null")
        if not isinstance(data.get("checks"), list) or not all(
            isinstance(item, dict) for item in data.get("checks", [])
        ):
            errors.append("checks must be an array of objects")
        if not isinstance(data.get("report_hashes"), dict):
            errors.append("report_hashes must be an object")
        else:
            for key in ("baselines", "checks"):
                values = data["report_hashes"].get(key, [])
                if not isinstance(values, list) or not all(
                    isinstance(value, str) and HASH_RE.fullmatch(value) for value in values
                ):
                    errors.append(f"report_hashes.{key} must be an array of SHA-256 hashes")
            verification_hash = data["report_hashes"].get("verification")
            if verification_hash is not None and (
                not isinstance(verification_hash, str) or not HASH_RE.fullmatch(verification_hash)
            ):
                errors.append("report_hashes.verification must be a SHA-256 hash or null")
            baseline_group = data.get("baseline_group")
            baseline_hashes = data["report_hashes"].get("baselines", [])
            if isinstance(baseline_group, dict) and baseline_hashes:
                records = baseline_group.get("reports", [])
                observed = [item.get("report_sha256") for item in records if isinstance(item, dict)]
                if observed != baseline_hashes:
                    errors.append(
                        "baseline_group report hashes do not match report_hashes.baselines"
                    )
            verification = data.get("verification")
            if isinstance(verification, dict):
                if (
                    verification_hash is not None
                    and verification.get("verification_report_sha256") != verification_hash
                ):
                    errors.append(
                        "verification report hash does not match report_hashes.verification"
                    )
                if (
                    baseline_hashes
                    and verification.get("baseline_report_hashes") != baseline_hashes
                ):
                    errors.append(
                        "verification baseline report hashes do not match report_hashes.baselines"
                    )
                if baseline_hashes and isinstance(data.get("baseline_group"), dict):
                    selected_run_id = verification.get("baseline_run_id")
                    selected_record = next(
                        (
                            item
                            for item in data["baseline_group"].get("reports", [])
                            if isinstance(item, dict) and item.get("run_id") == selected_run_id
                        ),
                        None,
                    )
                    if (
                        selected_record is not None
                        and verification.get("baseline_report_hash_match") is True
                        and verification.get("baseline_report_sha256")
                        != selected_record.get("report_sha256")
                    ):
                        errors.append(
                            "verification baseline report SHA-256 does not match its selected run"
                        )
            check_hashes = data["report_hashes"].get("checks", [])
            if check_hashes:
                check_records = data.get("checks", [])
                observed_checks = [
                    item.get("report_sha256") for item in check_records if isinstance(item, dict)
                ]
                if observed_checks != check_hashes:
                    errors.append("check report hashes do not match report_hashes.checks")
        for index, check in enumerate(data.get("checks", [])):
            if not isinstance(check, dict):
                continue
            outcome = check.get("outcome", check.get("status"))
            if outcome not in {"passed", "failed", "inconclusive"}:
                errors.append(f"checks[{index}].outcome must be passed, failed, or inconclusive")
            if "status" in check and check.get("status") != outcome:
                errors.append(f"checks[{index}].status must match checks[{index}].outcome")
        if (
            data.get("receipt_mode") != "trace-oriented"
            and isinstance(data.get("verification"), dict)
            and data["verification"].get("outcome") == "verified"
        ):
            required_true = (
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
            if any(data["verification"].get(key) is not True for key in required_true):
                errors.append("verified core receipt must have every identity comparison true")
            if data["verification"].get("identity_complete") is not True:
                errors.append("verified core receipt must have complete identity metadata")
            if data["verification"].get("baseline_report_hash_match") is not True:
                errors.append("verified core receipt must match the selected baseline report hash")
    if errors:
        raise SchemaValidationError("receipt validation failed: " + "; ".join(errors))


def load_receipt(path: Path) -> CodexMaintenanceReceipt:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"could not read receipt JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaValidationError("receipt JSON root must be an object")
    validate_receipt_dict(data)
    return CodexMaintenanceReceipt(
        receipt_schema_version=data["receipt_schema_version"],
        receipt_type=data["receipt_type"],
        tool_version=data["tool_version"],
        generated_at=data["generated_at"],
        codex=data["codex"],
        repository=data["repository"],
        issue=data["issue"],
        baseline=data["baseline"],
        commands=data["commands"],
        verification=data["verification"],
        agents=data["agents"],
        trace=data["trace"],
        evidence=data["evidence"],
        claims=data["claims"],
        verdict=data["verdict"],
        warnings=data["warnings"],
        redactions=data["redactions"],
        unknown_events=data["unknown_events"],
        parse_errors=data["parse_errors"],
        receipt_mode=data.get("receipt_mode", "trace-oriented"),
        trace_status=data.get("trace_status", "present"),
        identity_mode=data.get("identity_mode", "local"),
        baseline_group=data.get("baseline_group"),
        checks=data.get("checks", []),
        report_hashes=data.get("report_hashes", {}),
    )


def render_receipt(receipt: CodexMaintenanceReceipt) -> str:
    data = receipt.as_dict()
    codex = data.get("codex") or {}
    trace = data.get("trace") or {}
    baseline_group = data.get("baseline_group") or {}
    session = codex.get("session_id") or codex.get("task_id") or "not supplied"
    lines = [
        "# Codex Maintenance Receipt",
        "",
        f"- Verdict: **{data['verdict']}**",
        f"- Receipt schema: `{data['receipt_schema_version']}`",
        f"- Tool: `{data['tool_version']}`",
        f"- Generated: `{data['generated_at']}`",
        f"- Identity mode: `{data.get('identity_mode', 'local')}`",
        "",
        "## Codex run",
        "",
        f"- CLI version: `{codex.get('cli_version') or 'not supplied'}`",
        f"- Session/task: `{session}`",
        f"- Trace status: `{data.get('trace_status')}`",
        f"- Trace SHA-256: `{trace.get('sha256') or 'not supplied'}`",
        f"- Adapter: `{codex.get('adapter') or 'not supplied'}`",
        f"- Raw trace persisted: `{codex.get('raw_trace_persisted', False)}`",
        "",
        "## Issue",
        "",
        f"- Source: `{data['issue'].get('source')}`",
        f"- URL: `{data['issue'].get('url') or 'not provided'}`",
        f"- Number: `{data['issue'].get('number') or 'not provided'}`",
        "",
        "## Repository provenance",
        "",
        f"- Root: `{data['repository'].get('root')}`",
        f"- HEAD: `{data['repository'].get('head_sha') or 'unknown'}`",
        f"- Branch: `{data['repository'].get('branch') or 'unknown'}`",
        f"- Dirty: `{data['repository'].get('dirty')}`",
        f"- Changed files: `{data['repository'].get('changed_files', [])}`",
        f"- Changed-file count: `{data['repository'].get('changed_files_recorded', 0)}` recorded "
        f"of `{data['repository'].get('changed_files_total', 0)}` total; "
        f"truncated `{data['repository'].get('changed_files_truncated', False)}`",
        "- Changed-file digest: "
        f"`{data['repository'].get('changed_files_sha256') or 'not available'}`",
        "",
        "## Baseline and verification",
        "",
        f"- Baseline: **{(data['baseline'] or {}).get('outcome', 'not supplied')}**",
        f"- Baseline group: **{baseline_group.get('stability', 'not supplied')}** "
        f"({baseline_group.get('run_count', 0)} run(s))",
        f"- Verification: **{data['verification'].get('outcome')}**",
        f"- Relation: {data['verification'].get('reason') or 'not supplied'}",
        "",
        "## Claims",
        "",
    ]
    if data["claims"]:
        lines.extend(
            f"- `{claim['id']}` `{claim['type']}`: **{claim['status']}** — {claim['reason']} "
            f"(evidence: `{', '.join(claim['evidence_ids']) or 'none'}`)"
            for claim in data["claims"]
        )
    else:
        lines.append("- None supplied")
    lines.extend(["", "## Commands", ""])
    if data["commands"]:
        lines.extend(
            f"- `{command.get('id')}` `{command.get('display_command') or command.get('argv')}` "
            f"→ exit `{command.get('exit_code')}`; timeout `{command.get('timed_out')}`"
            for command in data["commands"]
        )
    else:
        lines.append("- None")
    if data.get("checks"):
        lines.extend(
            [
                "",
                "## Additional checks",
                "",
                *(
                    f"- `{check.get('id')}` `{check.get('purpose')}`: "
                    f"**{check.get('outcome')}**; exit `{check.get('exit_code')}`"
                    for check in data["checks"]
                ),
            ]
        )
    for heading, key in (
        ("Warnings", "warnings"),
        ("Redactions", "redactions"),
        ("Parse errors", "parse_errors"),
    ):
        lines.extend(["", f"## {heading}", ""])
        values = data[key]
        lines.extend(f"- {item}" for item in values) if values else lines.append("- None")
    return "\n".join(lines) + "\n"


def write_receipt_files(
    receipt: CodexMaintenanceReceipt,
    output: Path,
) -> tuple[Path, Path]:
    """Write receipt.json and receipt.md to an explicit file or directory."""

    if output.suffix.lower() == ".json":
        directory = output.parent
        json_path = output
    else:
        directory = output
        json_path = directory / "receipt.json"
    try:
        root = ensure_output_dir(directory)
        json_path = safe_output_file(root, json_path.name)
        json_path.write_text(receipt.to_json(), encoding="utf-8", newline="\n")
        markdown_path = safe_output_file(root, "receipt.md")
        markdown_path.write_text(render_receipt(receipt), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise DependencyError(f"could not write receipt files under {directory}: {exc}") from exc
    return json_path, markdown_path
