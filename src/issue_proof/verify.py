"""Conservative post-fix verification using the same explicit command."""

from __future__ import annotations

from pathlib import Path

from .collector import _execution_info, _warnings_for_execution, detect_runtime, inspect_repository
from .executor import ExecutionLimits, execute_argv, parse_command
from .models import Report, new_report


def verify_argv_against_baseline(
    baseline: Report,
    *,
    argv: list[str],
    execution: dict,
    repo_root: Path,
) -> dict:
    """Classify a direct argv execution for the Codex receipt path.

    The JSON command-argv file is deliberately not round-tripped through a shell command
    string.  This keeps Windows paths with spaces and literal arguments stable.
    """

    del repo_root
    baseline_execution = baseline.execution
    baseline_outcome = baseline.reproduction.get("outcome")
    timed_out = bool(execution.get("timed_out", False))
    exit_code = execution.get("exit_code")
    if baseline_outcome != "reproduced":
        outcome = "inconclusive"
        reason = "Baseline was not a completed reproduced run, so a fix cannot be inferred."
    elif baseline_execution.timed_out or baseline_execution.exit_code is None:
        outcome = "inconclusive"
        reason = "Baseline timed out or had no exit code, so it is not a stable comparison point."
    elif baseline_execution.argv != argv:
        outcome = "inconclusive"
        reason = (
            "Verification argv differs from the baseline argv; the same reproduction was not run."
        )
    elif timed_out or exit_code is None:
        outcome = "inconclusive"
        reason = "Verification timed out or had no exit code."
    elif exit_code == 0:
        outcome = "verified"
        reason = (
            "Baseline reproduced with a non-zero exit, while the matching verification command "
            "exited 0."
        )
    else:
        outcome = "not-fixed"
        reason = f"The matching verification command still exited with code {exit_code}."
    return {
        "verification": {
            "outcome": outcome,
            "reason": reason,
            "baseline_run_id": baseline.run_id,
            "baseline_exit_code": baseline_execution.exit_code,
            "verification_exit_code": exit_code,
            "baseline_stability": baseline.reproduction.get("stability", "unknown"),
        },
        "execution": execution,
    }


def verify_against_baseline(
    baseline: Report,
    *,
    command: str,
    repo_root: Path,
    limits: ExecutionLimits | None = None,
) -> Report:
    """Run the supplied command and classify it without conflating tool errors and bug outcomes."""

    argv = parse_command(command)
    current_repository, warnings = inspect_repository(repo_root)
    runtime = detect_runtime()
    result = execute_argv(argv, cwd=Path(current_repository.root), limits=limits)
    execution = _execution_info(result)
    execution_warnings, security_events = _warnings_for_execution(execution)
    warnings.extend(execution_warnings)
    notes = [
        "Verification re-used the explicitly supplied command and did not modify source files.",
        "A single baseline run cannot establish deterministic reproduction or causality.",
    ]
    baseline_execution = baseline.execution
    if baseline.reproduction.get("outcome") != "reproduced":
        outcome = "inconclusive"
        reason = "Baseline was not a completed reproduced run, so a fix cannot be inferred."
    elif baseline_execution.timed_out or baseline_execution.exit_code is None:
        outcome = "inconclusive"
        reason = "Baseline timed out or had no exit code, so it is not a stable comparison point."
    elif baseline_execution.argv != execution.argv:
        outcome = "inconclusive"
        reason = (
            "Verification argv differs from the baseline argv; the same reproduction was not run."
        )
    elif execution.timed_out or execution.exit_code is None:
        outcome = "inconclusive"
        reason = "Verification timed out or had no exit code."
    elif execution.exit_code == 0:
        outcome = "verified"
        reason = (
            "Baseline reproduced with a non-zero exit, while the matching verification command "
            "exited 0."
        )
    else:
        outcome = "not-fixed"
        reason = f"The matching verification command still exited with code {execution.exit_code}."
    if baseline.execution.cwd and execution.cwd and baseline.execution.cwd != execution.cwd:
        warnings.append("verification cwd differs from baseline cwd")
    verification = {
        "outcome": outcome,
        "reason": reason,
        "baseline_run_id": baseline.run_id,
        "baseline_exit_code": baseline.execution.exit_code,
        "verification_exit_code": execution.exit_code,
        "baseline_stability": baseline.reproduction.get("stability", "unknown"),
    }
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
