"""Stable evidence data model, JSON serialization, and schema-level validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import __version__
from .errors import SchemaValidationError

SCHEMA_VERSION = "1.0.0"
OUTCOMES = {"reproduced", "not-reproduced", "inconclusive", "not-run"}
VERIFICATION_OUTCOMES = {"verified", "not-fixed", "inconclusive", "not-applicable"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class IssueInfo:
    source: str
    location: str
    url: str | None
    title: str
    body_summary_hash: str
    body_excerpt: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "location": self.location,
            "url": self.url,
            "title": self.title,
            "body_summary_hash": self.body_summary_hash,
            "body_excerpt": self.body_excerpt,
        }


@dataclass
class RepositoryInfo:
    root: str
    remote_url: str | None
    head_sha: str | None
    branch: str | None
    dirty: bool | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "remote_url": self.remote_url,
            "head_sha": self.head_sha,
            "branch": self.branch,
            "dirty": self.dirty,
        }


@dataclass
class ExecutionInfo:
    argv: list[str]
    display_command: str | None
    cwd: str | None
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    exit_code: int | None
    timed_out: bool
    stdout: dict[str, Any]
    stderr: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "argv": self.argv,
            "display_command": self.display_command,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass
class RuntimeInfo:
    os: str
    architecture: str
    versions: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {"os": self.os, "architecture": self.architecture, "versions": self.versions}


@dataclass
class Report:
    schema_version: str
    tool_version: str
    run_id: str
    created_at: str
    issue: IssueInfo
    repository: RepositoryInfo
    runtime: RuntimeInfo
    execution: ExecutionInfo
    artifacts: list[dict[str, Any]]
    reproduction: dict[str, Any]
    verification: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    security_events: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    codex: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "issue": self.issue.as_dict(),
            "repository": self.repository.as_dict(),
            "runtime": self.runtime.as_dict(),
            "execution": self.execution.as_dict(),
            "artifacts": self.artifacts,
            "reproduction": self.reproduction,
            "verification": self.verification,
            "warnings": self.warnings,
            "security_events": self.security_events,
            "notes": self.notes,
        }
        if self.codex is not None:
            data["codex"] = self.codex
        return data

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def empty_execution() -> ExecutionInfo:
    empty_stream = {
        "summary": "",
        "sha256": "0" * 64,
        "captured_bytes": 0,
        "truncated": False,
        "redacted": False,
    }
    return ExecutionInfo(
        argv=[],
        display_command=None,
        cwd=None,
        started_at=None,
        finished_at=None,
        duration_seconds=None,
        exit_code=None,
        timed_out=False,
        stdout=empty_stream.copy(),
        stderr=empty_stream.copy(),
    )


def report_from_dict(data: dict[str, Any]) -> Report:
    try:
        issue = data["issue"]
        repository = data["repository"]
        runtime = data["runtime"]
        execution = data["execution"]
        return Report(
            schema_version=data["schema_version"],
            tool_version=data["tool_version"],
            run_id=data["run_id"],
            created_at=data["created_at"],
            issue=IssueInfo(**issue),
            repository=RepositoryInfo(**repository),
            runtime=RuntimeInfo(**runtime),
            execution=ExecutionInfo(**execution),
            artifacts=list(data["artifacts"]),
            reproduction=dict(data["reproduction"]),
            verification=dict(data["verification"]),
            warnings=list(data.get("warnings", [])),
            security_events=list(data.get("security_events", [])),
            notes=list(data.get("notes", [])),
            codex=dict(data["codex"]) if isinstance(data.get("codex"), dict) else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaValidationError(
            f"report cannot be loaded as the evidence model: {exc}"
        ) from exc


def load_report(path: Path) -> Report:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"could not read report JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaValidationError("report JSON root must be an object")
    validate_report_dict(data)
    return report_from_dict(data)


def _require(
    data: dict[str, Any], key: str, kind: type | tuple[type, ...], errors: list[str]
) -> Any:
    if key not in data:
        errors.append(f"missing required field: {key}")
        return None
    if not isinstance(data[key], kind):
        errors.append(f"field {key} must be {kind}")
    return data[key]


def _validate_stream(stream: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(stream, dict):
        errors.append(f"{prefix} must be an object")
        return
    for key in ("summary", "sha256", "captured_bytes", "truncated", "redacted"):
        _require(stream, key, (str, int, bool), errors)
    if not isinstance(stream.get("summary"), str):
        errors.append(f"{prefix}.summary must be a string")
    if not isinstance(stream.get("sha256"), str) or not HASH_RE.fullmatch(stream.get("sha256", "")):
        errors.append(f"{prefix}.sha256 must be a lowercase SHA-256 hash")
    if not isinstance(stream.get("captured_bytes"), int) or stream.get("captured_bytes", -1) < 0:
        errors.append(f"{prefix}.captured_bytes must be a non-negative integer")
    for key in ("truncated", "redacted"):
        if not isinstance(stream.get(key), bool):
            errors.append(f"{prefix}.{key} must be boolean")


def validate_report_dict(data: dict[str, Any]) -> None:
    """Validate the contract used by the bundled JSON Schema without third-party packages."""

    errors: list[str] = []
    for key in (
        "schema_version",
        "tool_version",
        "run_id",
        "created_at",
        "issue",
        "repository",
        "runtime",
        "execution",
        "artifacts",
        "reproduction",
        "verification",
        "warnings",
        "security_events",
        "notes",
    ):
        if key not in data:
            errors.append(f"missing required field: {key}")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("tool_version", "run_id"):
        if key in data and not isinstance(data[key], str):
            errors.append(f"{key} must be a string")
    if not isinstance(data.get("created_at"), str) or not ISO_RE.fullmatch(
        data.get("created_at", "")
    ):
        errors.append("created_at must be a timezone-aware ISO-8601 timestamp")

    issue = data.get("issue")
    if not isinstance(issue, dict):
        errors.append("issue must be an object")
    else:
        for key in ("source", "location", "title", "body_summary_hash", "body_excerpt"):
            _require(issue, key, str, errors)
        if issue.get("source") not in {"local-file", "github-url"}:
            errors.append("issue.source has an unsupported value")
        if not isinstance(issue.get("body_summary_hash"), str) or not HASH_RE.fullmatch(
            issue.get("body_summary_hash", "")
        ):
            errors.append("issue.body_summary_hash must be a lowercase SHA-256 hash")
        if (
            "url" not in issue
            or issue.get("url") is not None
            and not isinstance(issue.get("url"), str)
        ):
            errors.append("issue.url must be a string or null")

    repository = data.get("repository")
    if not isinstance(repository, dict):
        errors.append("repository must be an object")
    else:
        _require(repository, "root", str, errors)
        for key in ("remote_url", "head_sha", "branch"):
            if (
                key not in repository
                or repository[key] is not None
                and not isinstance(repository[key], str)
            ):
                errors.append(f"repository.{key} must be a string or null")
        if repository.get("head_sha") is not None and not re.fullmatch(
            r"[0-9a-f]{40,64}", repository["head_sha"]
        ):
            errors.append("repository.head_sha must look like a Git SHA")
        if not isinstance(repository.get("dirty"), (bool, type(None))):
            errors.append("repository.dirty must be boolean or null")

    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("runtime must be an object")
    else:
        for key in ("os", "architecture"):
            _require(runtime, key, str, errors)
        if not isinstance(runtime.get("versions"), dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in runtime.get("versions", {}).items()
        ):
            errors.append("runtime.versions must be an object of strings")

    execution = data.get("execution")
    if not isinstance(execution, dict):
        errors.append("execution must be an object")
    else:
        _require(execution, "argv", list, errors)
        if not all(isinstance(item, str) for item in execution.get("argv", [])):
            errors.append("execution.argv must contain only strings")
        for key in ("display_command", "cwd", "started_at", "finished_at"):
            if (
                key not in execution
                or execution[key] is not None
                and not isinstance(execution[key], str)
            ):
                errors.append(f"execution.{key} must be a string or null")
        if execution.get("started_at") is not None and not ISO_RE.fullmatch(
            execution["started_at"]
        ):
            errors.append("execution.started_at must be ISO-8601 or null")
        if execution.get("finished_at") is not None and not ISO_RE.fullmatch(
            execution["finished_at"]
        ):
            errors.append("execution.finished_at must be ISO-8601 or null")
        if not isinstance(execution.get("duration_seconds"), (int, float, type(None))):
            errors.append("execution.duration_seconds must be a number or null")
        if not isinstance(execution.get("exit_code"), (int, type(None))):
            errors.append("execution.exit_code must be an integer or null")
        if not isinstance(execution.get("timed_out"), bool):
            errors.append("execution.timed_out must be boolean")
        _validate_stream(execution.get("stdout"), "execution.stdout", errors)
        _validate_stream(execution.get("stderr"), "execution.stderr", errors)

    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be an array")
    else:
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                errors.append(f"artifacts[{index}] must be an object")
                continue
            for key in ("path", "sha256", "size_bytes"):
                _require(artifact, key, (str, int), errors)
            artifact_path = artifact.get("path", "")
            if (
                not isinstance(artifact_path, str)
                or Path(artifact_path).is_absolute()
                or ".." in Path(artifact_path).parts
                or re.match(r"^(?:[A-Za-z]:[\\/]|[\\]{2})", artifact_path)
            ):
                errors.append(f"artifacts[{index}].path must be relative")
            if not isinstance(artifact.get("sha256"), str) or not HASH_RE.fullmatch(
                artifact.get("sha256", "")
            ):
                errors.append(f"artifacts[{index}].sha256 must be a lowercase SHA-256 hash")
            if (
                not isinstance(artifact.get("size_bytes"), int)
                or artifact.get("size_bytes", -1) < 0
            ):
                errors.append(f"artifacts[{index}].size_bytes must be non-negative")

    reproduction = data.get("reproduction")
    if not isinstance(reproduction, dict):
        errors.append("reproduction must be an object")
    elif reproduction.get("outcome") not in OUTCOMES:
        errors.append("reproduction.outcome has an unsupported value")

    verification = data.get("verification")
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
    elif verification.get("outcome") not in VERIFICATION_OUTCOMES:
        errors.append("verification.outcome has an unsupported value")
    for key in ("warnings", "security_events", "notes"):
        if not isinstance(data.get(key), list) or not all(
            isinstance(item, str) for item in data.get(key, [])
        ):
            errors.append(f"{key} must be an array of strings")
    if "codex" in data and data["codex"] is not None and not isinstance(data["codex"], dict):
        errors.append("codex must be an object or null")
    if errors:
        raise SchemaValidationError("schema validation failed: " + "; ".join(errors))


def new_report(
    *,
    issue: IssueInfo,
    repository: RepositoryInfo,
    runtime: RuntimeInfo,
    execution: ExecutionInfo,
    artifacts: list[dict[str, Any]],
    reproduction: dict[str, Any],
    verification: dict[str, Any],
    warnings: list[str] | None = None,
    security_events: list[str] | None = None,
    notes: list[str] | None = None,
    codex: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> Report:
    return Report(
        schema_version=SCHEMA_VERSION,
        tool_version=__version__,
        run_id=str(uuid4()),
        created_at=created_at or utc_now(),
        issue=issue,
        repository=repository,
        runtime=runtime,
        execution=execution,
        artifacts=artifacts,
        reproduction=reproduction,
        verification=verification,
        warnings=warnings or [],
        security_events=security_events or [],
        notes=notes or [],
        codex=codex,
    )
