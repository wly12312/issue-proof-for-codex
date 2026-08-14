"""Conservative post-fix verification using canonical argv and execution identity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from .collector import (
    _execution_info,
    _warnings_for_execution,
    apply_identity_mode,
    detect_runtime,
    inspect_repository,
)
from .executor import ExecutionLimits, execute_argv, parse_command
from .identity import (
    argv_identity,
    cwd_identity,
    repository_identity,
    runtime_identity,
    timeout_policy_identity,
    tool_identity,
)
from .models import Report, RepositoryInfo, new_report
from .redact import redact_text


def _argv_can_be_compared(baseline_argv: list[str], current_argv: list[str]) -> bool:
    return (
        bool(baseline_argv)
        and bool(current_argv)
        and not any("[REDACTED]" in item for item in baseline_argv)
        and not any(redact_text(item).redacted for item in current_argv)
    )


def _same_optional(left: Any, right: Any) -> bool | None:
    if left is None and right is None:
        return None
    if left is None or right is None:
        return False
    return left == right


def _prepare_execution(
    execution: dict[str, Any],
    *,
    argv: list[str],
    repo_root: Path,
    baseline: Report,
) -> dict[str, Any]:
    current = dict(execution)
    current["argv"] = list(current.get("argv") or argv)
    current.setdefault("cwd", str(repo_root.resolve()))
    current.setdefault("cwd_identity", cwd_identity(current["cwd"]))
    current.setdefault("argv_identity", argv_identity(argv))
    for key in (
        "timeout_seconds",
        "termination_policy",
        "capture_limits",
        "timeout_policy_identity",
    ):
        if key not in current:
            current[key] = getattr(baseline.execution, key)
    return current


def _comparison_values(
    baseline: Report,
    current_repository: RepositoryInfo,
    current_execution: dict[str, Any],
    argv: list[str],
    current_runtime: dict[str, Any],
    current_tool_version: str,
) -> dict[str, bool | None]:
    baseline_execution = baseline.execution
    baseline_argv = baseline_execution.argv
    current_argv = current_execution.get("argv")
    same_argv = _same_optional(
        argv_identity(baseline_argv)
        if _argv_can_be_compared(baseline_argv, baseline_argv)
        else None,
        argv_identity(current_argv)
        if isinstance(current_argv, list) and _argv_can_be_compared(current_argv, current_argv)
        else None,
    )
    same_cwd = _same_optional(
        cwd_identity(baseline_execution.cwd) if baseline_execution.cwd else None,
        cwd_identity(current_execution["cwd"]) if current_execution.get("cwd") else None,
    )
    same_repository = _same_optional(
        repository_identity(baseline.repository.root, baseline.repository.remote_url),
        repository_identity(current_repository.root, current_repository.remote_url),
    )
    same_remote = _same_optional(
        baseline.repository.remote_url,
        current_repository.remote_url,
    )
    same_head = _same_optional(baseline.repository.head_sha, current_repository.head_sha)
    same_timeout = _same_optional(
        baseline_execution.timeout_seconds,
        current_execution.get("timeout_seconds"),
    )
    same_termination = _same_optional(
        baseline_execution.termination_policy,
        current_execution.get("termination_policy"),
    )
    baseline_policy = timeout_policy_identity(
        baseline_execution.timeout_seconds,
        baseline_execution.termination_policy,
        baseline_execution.capture_limits,
    )
    current_policy = timeout_policy_identity(
        current_execution.get("timeout_seconds"),
        current_execution.get("termination_policy"),
        current_execution.get("capture_limits"),
    )
    same_timeout_policy = _same_optional(baseline_policy, current_policy)
    same_runtime = _same_optional(
        runtime_identity(baseline.runtime.as_dict()) if baseline.runtime.as_dict() else None,
        runtime_identity(current_runtime) if current_runtime else None,
    )
    same_tool = _same_optional(
        tool_identity(baseline.tool_version),
        tool_identity(current_tool_version),
    )
    return {
        "same_argv": same_argv,
        "same_cwd": same_cwd,
        "same_repository": same_repository,
        "same_remote": same_remote,
        "same_head": same_head,
        "same_timeout": same_timeout,
        "same_termination_policy": same_termination,
        "same_timeout_policy": same_timeout_policy,
        "same_runtime": same_runtime,
        "same_tool": same_tool,
    }


def _classify(
    baseline: Report,
    *,
    argv: list[str],
    execution: dict[str, Any],
    current_repository: RepositoryInfo,
    current_runtime: dict[str, Any],
    current_tool_version: str,
    baseline_report_sha256: str | None = None,
) -> dict[str, Any]:
    comparisons = _comparison_values(
        baseline,
        current_repository,
        execution,
        argv,
        current_runtime,
        current_tool_version,
    )
    baseline_execution = baseline.execution
    baseline_outcome = baseline.reproduction.get("outcome")
    timed_out = bool(execution.get("timed_out", False))
    exit_code = execution.get("exit_code")
    for key, message in (
        ("same_repository", "Verification repository identity differs from the baseline."),
        ("same_remote", "Verification remote differs from the baseline."),
        ("same_head", "Verification HEAD/commit identity differs from the baseline."),
        ("same_cwd", "Verification cwd differs from the baseline."),
        ("same_argv", "Verification argv differs from the baseline."),
        ("same_timeout", "Verification timeout policy differs from the baseline."),
        ("same_termination_policy", "Verification termination policy differs from the baseline."),
        (
            "same_timeout_policy",
            "Verification capture/timeout policy identity differs from the baseline.",
        ),
        ("same_runtime", "Verification runtime identity differs from the baseline."),
        ("same_tool", "Verification IssueProof tool identity differs from the baseline."),
    ):
        if comparisons[key] is False:
            outcome = "inconclusive"
            reason = message
            break
    else:
        required_identity = (
            "same_repository",
            "same_remote",
            "same_head",
            "same_cwd",
            "same_argv",
            "same_timeout",
            "same_termination_policy",
            "same_timeout_policy",
            "same_runtime",
            "same_tool",
        )
        if any(comparisons[key] is None for key in required_identity):
            outcome = "inconclusive"
            reason = "Verification identity metadata is incomplete."
        elif baseline_outcome != "reproduced":
            outcome = "inconclusive"
            reason = "Baseline was not a completed reproduced run, so a fix cannot be inferred."
        elif (
            baseline_execution.timed_out
            or baseline_execution.exit_code is None
            or baseline_execution.exit_code == 0
        ):
            outcome = "inconclusive"
            reason = (
                "Baseline timed out, had no exit code, or exited 0, so it is not a reproduced "
                "failure and cannot be used as a stable comparison point."
            )
        elif timed_out or exit_code is None:
            outcome = "inconclusive"
            reason = "Verification timed out or had no exit code."
        elif exit_code == 0:
            outcome = "verified"
            reason = (
                "The matching verification command exited 0 after a completed non-zero baseline."
            )
        else:
            outcome = "not-fixed"
            reason = f"The matching verification command still exited with code {exit_code}."
    verification = {
        "outcome": outcome,
        "reason": reason,
        "baseline_run_id": baseline.run_id,
        "baseline_group_id": baseline.reproduction.get("baseline_group_id"),
        "baseline_exit_code": baseline_execution.exit_code,
        "verification_exit_code": exit_code,
        "baseline_stability": baseline.reproduction.get("stability", "unknown"),
        "baseline_report_sha256": baseline_report_sha256,
        **comparisons,
        "identity_complete": all(
            comparisons[key] is not None
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
        ),
    }
    return {"verification": verification, "execution": execution}


def verify_argv_against_baseline(
    baseline: Report,
    *,
    argv: list[str],
    execution: dict[str, Any],
    repo_root: Path,
    baseline_report_sha256: str | None = None,
    identity_mode: str | None = None,
) -> dict[str, Any]:
    """Classify a direct argv execution without shell round-tripping."""

    current_repository, warnings = inspect_repository(repo_root)
    apply_identity_mode(
        current_repository,
        warnings,
        identity_mode or baseline.repository.identity_mode or "local",
    )
    current_runtime = detect_runtime().as_dict()
    current_execution = _prepare_execution(
        execution,
        argv=argv,
        repo_root=repo_root,
        baseline=baseline,
    )
    return _classify(
        baseline,
        argv=argv,
        execution=current_execution,
        current_repository=current_repository,
        current_runtime=current_runtime,
        current_tool_version=__version__,
        baseline_report_sha256=baseline_report_sha256,
    )


def verify_against_baseline(
    baseline: Report,
    *,
    command: str | None = None,
    argv: list[str] | None = None,
    repo_root: Path,
    limits: ExecutionLimits | None = None,
    baseline_report_sha256: str | None = None,
    identity_mode: str | None = None,
) -> Report:
    """Run the supplied explicit command and classify it against a baseline."""

    if command is not None and argv is not None:
        raise ValueError("command and argv are mutually exclusive")
    selected_argv = list(argv) if argv is not None else parse_command(command or "")
    current_repository, warnings = inspect_repository(repo_root)
    apply_identity_mode(
        current_repository,
        warnings,
        identity_mode or baseline.repository.identity_mode or "local",
    )
    runtime = detect_runtime()
    selected_limits = limits or ExecutionLimits()
    result = execute_argv(selected_argv, cwd=repo_root.resolve(), limits=selected_limits)
    execution = _execution_info(result)
    execution_warnings, security_events = _warnings_for_execution(execution)
    warnings.extend(execution_warnings)
    classified = _classify(
        baseline,
        argv=selected_argv,
        execution=execution.as_dict(),
        current_repository=current_repository,
        current_runtime=runtime.as_dict(),
        current_tool_version=__version__,
        baseline_report_sha256=baseline_report_sha256,
    )
    verification = classified["verification"]
    notes = [
        (
            "IssueProof did not edit source files; the explicitly supplied command may have "
            "side effects."
        ),
        "A single baseline run cannot establish deterministic reproduction or causality.",
    ]
    reproduction = {
        "outcome": "inconclusive"
        if execution.timed_out
        else ("not-reproduced" if execution.exit_code == 0 else "reproduced"),
        "reason": "Verification command result; consult verification.outcome for the fix decision.",
        "stability": "single-run" if not execution.timed_out else "unknown",
    }
    return new_report(
        issue=baseline.issue,
        repository=current_repository,
        runtime=runtime,
        execution=execution,
        artifacts=[],
        reproduction=reproduction,
        verification=verification,
        warnings=warnings,
        security_events=security_events,
        notes=notes,
    )
