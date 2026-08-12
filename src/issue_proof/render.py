"""Deterministic human-readable rendering for evidence reports."""

from __future__ import annotations

from typing import Any


def _value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def render_report(report) -> str:
    data = report.as_dict()
    issue = data["issue"]
    repository = data["repository"]
    runtime = data["runtime"]
    execution = data["execution"]
    reproduction = data["reproduction"]
    verification = data["verification"]
    lines = [
        "# Issue Proof Evidence",
        "",
        f"- Run ID: `{data['run_id']}`",
        f"- Created at: `{data['created_at']}`",
        f"- Schema: `{data['schema_version']}`",
        f"- Tool: `{data['tool_version']}`",
        "",
        "## Issue",
        "",
        f"- Source: `{issue['source']}`",
        f"- Location: `{issue['location']}`",
        f"- Title: {_value(issue['title'])}",
        f"- Body summary SHA-256: `{issue['body_summary_hash']}`",
        "",
        "### Sanitized issue excerpt",
        "",
        "```text",
        issue["body_excerpt"],
        "```",
        "",
        "## Repository",
        "",
        f"- Root: `{repository['root']}`",
        f"- Remote: `{_value(repository['remote_url'])}`",
        f"- HEAD: `{_value(repository['head_sha'])}`",
        f"- Branch: `{_value(repository['branch'])}`",
        f"- Dirty: {_value(repository['dirty'])}",
        "",
        "## Runtime",
        "",
        f"- OS: `{runtime['os']}`",
        f"- Architecture: `{runtime['architecture']}`",
    ]
    for name, version in runtime["versions"].items():
        lines.append(f"- {name}: `{version}`")
    lines.extend(
        [
            "",
            "## Execution",
            "",
            f"- Command: `{_value(execution['display_command'])}`",
            f"- Argv: `{execution['argv']}`",
            f"- CWD: `{_value(execution['cwd'])}`",
            f"- Started: `{_value(execution['started_at'])}`",
            f"- Finished: `{_value(execution['finished_at'])}`",
            f"- Duration seconds: `{_value(execution['duration_seconds'])}`",
            f"- Exit code: `{_value(execution['exit_code'])}`",
            f"- Timed out: {_value(execution['timed_out'])}",
            "",
            "### stdout",
            "",
            f"- SHA-256: `{execution['stdout']['sha256']}`",
            f"- Captured bytes: `{execution['stdout']['captured_bytes']}`",
            "- Truncated: "
            f"{_value(execution['stdout']['truncated'])}; redacted: "
            f"{_value(execution['stdout']['redacted'])}",
            "",
            "```text",
            execution["stdout"]["summary"],
            "```",
            "",
            "### stderr",
            "",
            f"- SHA-256: `{execution['stderr']['sha256']}`",
            f"- Captured bytes: `{execution['stderr']['captured_bytes']}`",
            "- Truncated: "
            f"{_value(execution['stderr']['truncated'])}; redacted: "
            f"{_value(execution['stderr']['redacted'])}",
            "",
            "```text",
            execution["stderr"]["summary"],
            "```",
            "",
            "## Outcomes",
            "",
            f"- Reproduction: **{reproduction['outcome']}** — {reproduction.get('reason', '')}",
            f"- Verification: **{verification['outcome']}** — {verification.get('reason', '')}",
            "",
            "## Artifacts",
            "",
        ]
    )
    if data["artifacts"]:
        lines.extend(
            f"- `{item['path']}` — {item['size_bytes']} bytes — `{item['sha256']}`"
            for item in data["artifacts"]
        )
    else:
        lines.append("- None")
    for heading, key in (
        ("Warnings", "warnings"),
        ("Security events", "security_events"),
        ("Notes", "notes"),
    ):
        lines.extend(["", f"## {heading}", ""])
        values = data[key]
        lines.extend(f"- {item}" for item in values) if values else lines.append("- None")
    return "\n".join(lines) + "\n"
