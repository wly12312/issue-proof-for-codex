"""Collect issue, repository, runtime, and command evidence into a report."""

from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from .errors import DependencyError, OutputPathError
from .executor import ExecutionLimits, execute_argv, parse_command
from .identity import (
    argv_identity,
    cwd_identity,
    repository_identity,
    timeout_policy_identity,
)
from .models import (
    ExecutionInfo,
    IssueInfo,
    Report,
    RepositoryInfo,
    RuntimeInfo,
    empty_execution,
    new_report,
)
from .redact import redact_text, sha256_bytes, sha256_text
from .render import render_report


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return path.is_symlink()
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def ensure_output_dir(path: Path) -> Path:
    if (path.exists() or path.is_symlink()) and _is_reparse_point(path):
        raise OutputPathError(f"output directory must not be a reparse point: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
        resolved = path.resolve()
    except OSError as exc:
        raise OutputPathError(f"could not create output directory {path}: {exc}") from exc
    if not resolved.is_dir():
        raise OutputPathError(f"output path is not a directory: {path}")
    return resolved


def safe_output_file(output_dir: Path, relative_name: str) -> Path:
    """Resolve a child output path and reject traversal, absolute paths, and symlink escapes."""

    candidate_name = Path(relative_name)
    # A single leading backslash is rooted on Windows even without a drive;
    # reject it here because POSIX Path does not classify it as absolute.
    windows_absolute = bool(re.match(r"^(?:[A-Za-z]:|[\\/])", relative_name))
    if candidate_name.is_absolute() or windows_absolute or ".." in candidate_name.parts:
        raise OutputPathError(f"output file must stay inside the output directory: {relative_name}")
    root = output_dir.resolve()
    candidate = (root / candidate_name).resolve(strict=False)
    if not _is_within(root, candidate):
        raise OutputPathError(f"output file escapes the output directory: {relative_name}")
    existing = root
    for part in candidate.relative_to(root).parts:
        existing = existing / part
        if (existing.exists() or existing.is_symlink()) and _is_reparse_point(existing):
            raise OutputPathError(f"output path contains a reparse point: {relative_name}")
    return candidate


def read_issue_file(path: Path) -> tuple[str, bool]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DependencyError(f"could not read issue file {path}: {exc}") from exc
    text = raw.decode("utf-8", errors="replace")
    return text, "\ufffd" in text


def issue_info_from_payload(
    source: str, location: str, body: str, title: str, url: str | None
) -> tuple[IssueInfo, str]:
    redacted = redact_text(body)
    clean_body = redacted.text.replace("\r\n", "\n")
    excerpt = clean_body[:4000]
    if len(clean_body) > len(excerpt):
        excerpt += "\n[issue body excerpt truncated]"
    clean_title = redact_text(title).text.strip() or "Untitled issue"
    info = IssueInfo(
        source=source,
        location=redact_text(location).text,
        url=redact_text(url).text if url else None,
        title=clean_title,
        body_summary_hash=sha256_text(clean_body),
        body_excerpt=excerpt,
    )
    return info, clean_body


def _git_command(args: list[str], cwd: Path, timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError) as exc:
        raise DependencyError(f"Git is required to inspect the repository: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DependencyError(f"Git command timed out: git {' '.join(args)}") from exc
    return (
        result.returncode,
        result.stdout.decode("utf-8", errors="replace").strip(),
        result.stderr.decode("utf-8", errors="replace").strip(),
    )


def inspect_repository(repo_root: Path) -> tuple[RepositoryInfo, list[str]]:
    root = repo_root.resolve()
    warnings: list[str] = []
    code, git_root, _ = _git_command(["rev-parse", "--show-toplevel"], root)
    if code != 0 or not git_root:
        warnings.append("repository is not a Git worktree; Git revision fields are unavailable")
        return RepositoryInfo(
            root=redact_text(str(root)).text,
            remote_url=None,
            head_sha=None,
            branch=None,
            dirty=None,
            identity=repository_identity(root),
        ), warnings
    actual_root = Path(git_root).resolve()
    _, head, head_err = _git_command(["rev-parse", "HEAD"], actual_root)
    _, branch, _ = _git_command(["branch", "--show-current"], actual_root)
    remote_code, remote, _ = _git_command(["config", "--get", "remote.origin.url"], actual_root)
    status_code, status, _ = _git_command(["status", "--porcelain"], actual_root)
    if head_err or not head:
        head = None
        warnings.append("Git repository has no commit yet; HEAD SHA is unavailable")
    if remote_code != 0:
        remote = None
    if status_code != 0:
        dirty: bool | None = None
        warnings.append("could not determine Git dirty state")
    else:
        dirty = bool(status)
    return (
        RepositoryInfo(
            root=redact_text(str(actual_root)).text,
            remote_url=redact_text(remote).text if remote else None,
            head_sha=head,
            branch=branch or "(detached)",
            dirty=dirty,
            identity=repository_identity(actual_root, remote or None),
        ),
        warnings,
    )


def apply_identity_mode(
    repository: RepositoryInfo,
    warnings: list[str],
    identity_mode: str,
) -> None:
    """Record the workflow identity policy and enforce GitHub-grade prerequisites."""

    if identity_mode not in {"github", "local"}:
        raise ValueError("identity_mode must be github or local")
    repository.identity_mode = identity_mode
    missing: list[str] = []
    if not repository.remote_url:
        missing.append("remote URL")
    if not repository.head_sha:
        missing.append("HEAD SHA")
    if not missing:
        return
    if identity_mode == "github":
        raise DependencyError(
            "GitHub identity mode requires a non-empty remote URL and HEAD SHA; "
            f"missing {', '.join(missing)}"
        )
    warnings.append(
        "local identity mode selected; missing "
        f"{', '.join(missing)} forces any receipt to downgrade to inconclusive"
    )


def _runtime_version(executable: str, args: list[str]) -> str | None:
    if not shutil.which(executable):
        return None
    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            check=False,
            shell=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("utf-8", errors="replace") or result.stderr.decode(
        "utf-8", errors="replace"
    )
    text = redact_text(text.strip()).text
    return text[:256] if text else None


def detect_runtime() -> RuntimeInfo:
    versions: dict[str, str] = {"python": platform.python_version()}
    for name, executable, args in (
        ("node", "node", ["--version"]),
        ("rust", "rustc", ["--version"]),
        ("java", "java", ["-version"]),
    ):
        version = _runtime_version(executable, args)
        if version:
            versions[name] = version
    return RuntimeInfo(os=platform.system(), architecture=platform.machine(), versions=versions)


def _execution_info(result) -> ExecutionInfo:
    def safe(value: str) -> str:
        return redact_text(value).text

    return ExecutionInfo(
        argv=[safe(item) for item in result.argv],
        display_command=safe(result.display_command),
        cwd=safe(result.cwd),
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_seconds=result.duration_seconds,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        stdout={
            "summary": result.stdout.summary,
            "sha256": result.stdout.sha256,
            "captured_bytes": result.stdout.captured_bytes,
            "truncated": result.stdout.truncated,
            "redacted": result.stdout.redacted,
        },
        stderr={
            "summary": result.stderr.summary,
            "sha256": result.stderr.sha256,
            "captured_bytes": result.stderr.captured_bytes,
            "truncated": result.stderr.truncated,
            "redacted": result.stderr.redacted,
        },
        timeout_seconds=getattr(result, "timeout_seconds", None),
        termination_policy=getattr(result, "termination_policy", None),
        capture_limits=getattr(result, "capture_limits", None),
        argv_identity=argv_identity(result.argv),
        cwd_identity=cwd_identity(result.cwd),
        timeout_policy_identity=timeout_policy_identity(
            getattr(result, "timeout_seconds", None),
            getattr(result, "termination_policy", None),
            getattr(result, "capture_limits", None),
        ),
    )


def _reproduction(execution: ExecutionInfo) -> dict[str, Any]:
    if not execution.argv:
        return {"outcome": "not-run", "reason": "No explicit command was supplied."}
    if execution.timed_out or execution.exit_code is None:
        return {
            "outcome": "inconclusive",
            "reason": "The command did not finish within the configured timeout.",
            "stability": "unknown",
        }
    if execution.exit_code == 0:
        return {
            "outcome": "not-reproduced",
            "reason": "The explicitly supplied command exited with code 0.",
            "stability": "single-run",
        }
    return {
        "outcome": "reproduced",
        "reason": f"The explicitly supplied command exited with code {execution.exit_code}.",
        "stability": "single-run",
    }


def _warnings_for_execution(execution: ExecutionInfo) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    security_events: list[str] = []
    for stream_name in ("stdout", "stderr"):
        stream = getattr(execution, stream_name)
        if stream["truncated"]:
            warnings.append(
                f"{stream_name} exceeded the configured capture limit and was truncated"
            )
            security_events.append(f"{stream_name} capture was bounded")
        if stream["redacted"]:
            warnings.append(f"{stream_name} contained a redaction match")
            security_events.append(f"{stream_name} was sanitized before persistence")
    if execution.timed_out:
        warnings.append("command timed out; process-tree termination was requested")
        security_events.append("command timeout termination was requested")
    return warnings, security_events


def _artifact_for(path: Path, output_dir: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(output_dir)).replace(os.sep, "/"),
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
    }


def write_report_files(
    report: Report,
    output_dir: Path,
    *,
    issue_snapshot: str | None = None,
    max_files: int = 16,
) -> tuple[Path, Path]:
    root = ensure_output_dir(output_dir)
    if max_files <= 0:
        raise OutputPathError("max files must be greater than zero")
    if issue_snapshot is not None and len(report.artifacts) >= max_files:
        raise OutputPathError("artifact limit reached before writing the issue snapshot")
    if issue_snapshot is not None:
        snapshot_path = safe_output_file(root, "issue-source.md")
        snapshot_path.write_text(issue_snapshot, encoding="utf-8", newline="\n")
        if not report.artifacts:
            report.artifacts.append(_artifact_for(snapshot_path, root))
    json_path = safe_output_file(root, "report.json")
    markdown_path = safe_output_file(root, "report.md")
    json_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
    markdown_path.write_text(render_report(report), encoding="utf-8", newline="\n")
    return json_path, markdown_path


def collect_evidence(
    *,
    issue: IssueInfo,
    issue_snapshot: str,
    repo_root: Path,
    command: str | None,
    command_argv: list[str] | None = None,
    output_dir: Path,
    limits: ExecutionLimits | None = None,
    created_at: str | None = None,
    identity_mode: str = "local",
) -> tuple[Report, Path, Path]:
    selected_limits = limits or ExecutionLimits()
    repository, warnings = inspect_repository(repo_root)
    apply_identity_mode(repository, warnings, identity_mode)
    runtime = detect_runtime()
    execution = empty_execution()
    security_events: list[str] = []
    notes = [
        (
            "Issue text was treated as untrusted data; only an explicit command or "
            "--command-argv is executable."
        ),
        (
            "This baseline is one observation; a stable baseline group requires at least two "
            "matching runs."
        ),
        f"MVP artifact capture is limited to {selected_limits.max_files} files; "
        "repository files are not scanned.",
    ]
    if command is not None and command_argv is not None:
        raise ValueError("command and command_argv are mutually exclusive")
    if command is not None or command_argv is not None:
        argv = command_argv if command_argv is not None else parse_command(command or "")
        result = execute_argv(argv, cwd=repo_root.resolve(), limits=selected_limits)
        execution = _execution_info(result)
        execution_warnings, execution_security = _warnings_for_execution(execution)
        warnings.extend(execution_warnings)
        security_events.extend(execution_security)
    else:
        warnings.append("No command was supplied; static evidence was collected only")
    reproduction = _reproduction(execution)
    report = new_report(
        issue=issue,
        repository=repository,
        runtime=runtime,
        execution=execution,
        artifacts=[],
        reproduction=reproduction,
        verification={"outcome": "not-applicable", "reason": "This is a collection run."},
        warnings=warnings,
        security_events=security_events,
        notes=notes,
        created_at=created_at,
    )
    json_path, markdown_path = write_report_files(
        report,
        output_dir,
        issue_snapshot=issue_snapshot,
        max_files=selected_limits.max_files,
    )
    return report, json_path, markdown_path


def collect_from_issue_file(
    *,
    issue_file: Path,
    repo_root: Path,
    command: str | None,
    command_argv: list[str] | None = None,
    output_dir: Path,
    limits: ExecutionLimits | None = None,
    identity_mode: str = "local",
) -> tuple[Report, Path, Path]:
    if not issue_file.exists() or not issue_file.is_file():
        raise DependencyError(f"issue file does not exist or is not a file: {issue_file}")
    body, had_replacement = read_issue_file(issue_file)
    lines = body.splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), "")
    if not title:
        title = next((line.strip() for line in lines if line.strip()), "Untitled issue")[:160]
    issue, snapshot = issue_info_from_payload(
        "local-file", str(issue_file.resolve()), body, title, None
    )
    report, json_path, markdown_path = collect_evidence(
        issue=issue,
        issue_snapshot=snapshot,
        repo_root=repo_root,
        command=command,
        command_argv=command_argv,
        output_dir=output_dir,
        limits=limits,
        identity_mode=identity_mode,
    )
    if had_replacement:
        report.warnings.append(
            "Issue file contained invalid UTF-8; replacement characters were used"
        )
        report.security_events.append("Issue input was decoded with UTF-8 replacement characters")
        write_report_files(report, output_dir, max_files=(limits or ExecutionLimits()).max_files)
    return report, json_path, markdown_path
