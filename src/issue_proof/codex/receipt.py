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
from ..models import Report
from ..redact import REDACTION, redact_text, sha256_text
from .agents import AgentScan
from .claims import Claim, verify_claims
from .events import TraceSummary
from .git_provenance import GitProvenance, collect_git_provenance

RECEIPT_SCHEMA_VERSION = "1.0.0"
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


@dataclass
class CodexMaintenanceReceipt:
    """Portable, redacted evidence object for one Codex-assisted maintenance run."""

    receipt_schema_version: str
    receipt_type: str
    tool_version: str
    generated_at: str
    codex: dict[str, Any]
    repository: dict[str, Any]
    issue: dict[str, Any]
    baseline: dict[str, Any] | None
    commands: list[dict[str, Any]]
    verification: dict[str, Any]
    agents: dict[str, Any]
    trace: dict[str, Any]
    evidence: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    verdict: str
    warnings: list[str] = None  # type: ignore[assignment]
    redactions: list[str] = None  # type: ignore[assignment]
    unknown_events: list[str] = None  # type: ignore[assignment]
    parse_errors: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.warnings = list(self.warnings or [])
        self.redactions = list(self.redactions or [])
        self.unknown_events = list(self.unknown_events or [])
        self.parse_errors = list(self.parse_errors or [])

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
    }
    errors.extend(f"missing required field: {key}" for key in sorted(required - set(data)))
    errors.extend(f"unexpected field: {key}" for key in sorted(set(data) - required))
    if data.get("receipt_schema_version") != RECEIPT_SCHEMA_VERSION:
        errors.append(f"receipt_schema_version must be {RECEIPT_SCHEMA_VERSION}")
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
    if (
        not isinstance(trace, dict)
        or not isinstance(trace.get("sha256"), str)
        or not HASH_RE.fullmatch(trace.get("sha256", ""))
    ):
        errors.append("trace.sha256 must be a lowercase SHA-256 hash")
    if isinstance(trace, dict):
        for key in ("lines_seen", "valid_events", "unknown_event_count"):
            value = trace.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"trace.{key} must be a non-negative integer")
        for key in ("include_messages", "event_limit_reached"):
            if key in trace and not isinstance(trace[key], bool):
                errors.append(f"trace.{key} must be boolean")
    codex = data.get("codex")
    if (
        not isinstance(codex, dict)
        or not isinstance(codex.get("source_trace_sha256"), str)
        or not HASH_RE.fullmatch(codex.get("source_trace_sha256", ""))
    ):
        errors.append("codex.source_trace_sha256 must be a lowercase SHA-256 hash")
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
    )


def render_receipt(receipt: CodexMaintenanceReceipt) -> str:
    data = receipt.as_dict()
    session = data["codex"].get("session_id") or data["codex"].get("task_id") or "unknown"
    lines = [
        "# Codex Maintenance Receipt",
        "",
        f"- Verdict: **{data['verdict']}**",
        f"- Receipt schema: `{data['receipt_schema_version']}`",
        f"- Tool: `{data['tool_version']}`",
        f"- Generated: `{data['generated_at']}`",
        "",
        "## Codex run",
        "",
        f"- CLI version: `{data['codex'].get('cli_version') or 'unknown'}`",
        f"- Session/task: `{session}`",
        f"- Trace SHA-256: `{data['codex']['source_trace_sha256']}`",
        f"- Adapter: `{data['codex']['adapter']}`",
        f"- Raw trace persisted: `{data['codex']['raw_trace_persisted']}`",
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
