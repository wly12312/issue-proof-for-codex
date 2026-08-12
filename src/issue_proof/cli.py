"""Command-line interface for issue-proof."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .collector import (
    collect_from_issue_file,
    ensure_output_dir,
    issue_info_from_payload,
    read_issue_file,
    safe_output_file,
    write_report_files,
)
from .errors import IssueProofError
from .executor import ExecutionLimits
from .github import fetch_issue_via_gh, parse_issue_url
from .models import load_report
from .render import render_report
from .verify import verify_against_baseline, verify_argv_against_baseline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="issue-proof",
        description="Collect and verify safe, auditable evidence for open-source issues.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    doctor = subparsers.add_parser("doctor", help="check local runtime and optional dependencies")
    doctor.set_defaults(handler=_doctor)

    collect = subparsers.add_parser(
        "collect", help="collect an Issue and optional explicit command evidence"
    )
    source = collect.add_mutually_exclusive_group(required=True)
    source.add_argument("--issue-file", type=Path, help="local Markdown Issue file")
    source.add_argument("--issue-url", help="GitHub Issue URL fetched through authenticated gh")
    collect.add_argument("--command", help="explicit argv-style command; shell syntax is rejected")
    collect.add_argument("--output", type=Path, required=True, help="evidence output directory")
    collect.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="repository command cwd"
    )
    _add_limits(collect)
    collect.set_defaults(handler=_collect)

    verify = subparsers.add_parser(
        "verify", help="run the same explicit command against a baseline report"
    )
    verify.add_argument("--baseline", type=Path, required=True, help="baseline report.json")
    verify.add_argument("--command", required=True, help="explicit argv-style verification command")
    verify.add_argument("--output", type=Path, required=True, help="verification output directory")
    verify.add_argument("--repo-root", type=Path, default=Path.cwd(), help="repository command cwd")
    _add_limits(verify)
    verify.set_defaults(handler=_verify)

    validate = subparsers.add_parser(
        "validate", help="validate report.json against the bundled contract"
    )
    validate.add_argument("report", type=Path, help="report.json")
    validate.set_defaults(handler=_validate)

    render = subparsers.add_parser("render", help="render a report.json as deterministic Markdown")
    render.add_argument("report", type=Path, help="report.json")
    render.add_argument("--output", type=Path, help="write Markdown to this file instead of stdout")
    render.set_defaults(handler=_render)

    codex = subparsers.add_parser(
        "codex", help="import Codex JSONL traces and create a maintenance receipt"
    )
    codex_subparsers = codex.add_subparsers(dest="codex_command", required=True)

    codex_ingest = codex_subparsers.add_parser(
        "ingest", help="stream and summarize an explicit Codex JSONL trace"
    )
    codex_ingest.add_argument("--trace", type=Path, required=True)
    codex_ingest.add_argument("--output", type=Path, required=True)
    _add_trace_limits(codex_ingest)
    codex_ingest.set_defaults(handler=_codex_ingest)

    codex_receipt = codex_subparsers.add_parser(
        "receipt", help="create a standalone CodexMaintenanceReceipt from a trace"
    )
    codex_receipt.add_argument("--trace", type=Path, required=True)
    codex_receipt.add_argument("--output", type=Path, required=True)
    codex_receipt.add_argument("--issue-url")
    codex_receipt.add_argument("--issue-file", type=Path)
    codex_receipt.add_argument("--baseline", type=Path)
    codex_receipt.add_argument("--repo-root", type=Path, default=Path.cwd())
    codex_receipt.add_argument("--agents-target", default=".")
    codex_receipt.add_argument("--include-agents-content", action="store_true")
    codex_receipt.add_argument("--claims", type=Path)
    codex_receipt.add_argument("--include-messages", action="store_true")
    codex_receipt.add_argument("--heuristic-claims", action="store_true")
    _add_trace_limits(codex_receipt)
    codex_receipt.set_defaults(handler=_codex_receipt)

    codex_verify = codex_subparsers.add_parser(
        "verify", help="run an explicit argv JSON command against a baseline and make a receipt"
    )
    codex_verify.add_argument("--baseline", type=Path, required=True)
    codex_verify.add_argument("--trace", type=Path, required=True)
    codex_verify.add_argument("--command-argv", type=Path, required=True)
    codex_verify.add_argument("--output", type=Path, required=True)
    codex_verify.add_argument("--repo-root", type=Path, default=Path.cwd())
    codex_verify.add_argument("--issue-url")
    codex_verify.add_argument("--claims", type=Path)
    codex_verify.add_argument("--agents-target", default=".")
    codex_verify.add_argument("--include-agents-content", action="store_true")
    codex_verify.add_argument("--include-messages", action="store_true")
    codex_verify.add_argument("--heuristic-claims", action="store_true")
    _add_limits(codex_verify)
    _add_trace_limits(codex_verify)
    codex_verify.set_defaults(handler=_codex_verify)

    codex_doctor = codex_subparsers.add_parser(
        "doctor", help="detect local Codex CLI without starting a task"
    )
    codex_doctor.set_defaults(handler=_codex_doctor)

    codex_agents = codex_subparsers.add_parser(
        "agents", help="report repository-scoped AGENTS.md provenance"
    )
    codex_agents.add_argument("--repo", type=Path, required=True)
    codex_agents.add_argument("--target", default=".")
    codex_agents.add_argument("--include-content", action="store_true")
    codex_agents.set_defaults(handler=_codex_agents)
    return parser


def _add_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout", type=float, default=120.0, help="command timeout in seconds")
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        default=256_000,
        help="maximum captured bytes per output stream",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=16,
        help="maximum artifact files; MVP emits at most one sanitized snapshot",
    )


def _add_trace_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-line-bytes", type=int, default=1_000_000)
    parser.add_argument("--max-text-bytes", type=int, default=16_384)
    parser.add_argument("--max-events", type=int, default=50_000)
    parser.add_argument("--strict", action="store_true")


def _limits(args: argparse.Namespace) -> ExecutionLimits:
    if args.timeout <= 0 or args.max_output_bytes <= 0 or args.max_files <= 0:
        raise IssueProofError(
            "timeout, max-output-bytes, and max-files must be greater than zero", exit_code=2
        )
    return ExecutionLimits(
        timeout_seconds=args.timeout,
        max_output_bytes=args.max_output_bytes,
        max_files=args.max_files,
    )


def _trace_limits(args: argparse.Namespace):
    from .codex.parser import ParseLimits

    if args.max_line_bytes <= 0 or args.max_text_bytes <= 0 or args.max_events <= 0:
        raise IssueProofError(
            "max-line-bytes, max-text-bytes, and max-events must be greater than zero", exit_code=2
        )
    return ParseLimits(
        max_line_bytes=args.max_line_bytes,
        max_text_bytes=args.max_text_bytes,
        max_events=args.max_events,
    )


def _doctor(_: argparse.Namespace) -> int:
    print("issue-proof doctor")
    print(f"- Python: {platform.python_version()} ({sys.executable})")
    print(f"- OS: {platform.system()} {platform.machine()}")
    print(f"- Git: {shutil.which('git') or 'not found'}")
    print(f"- gh (optional, needed for --issue-url): {shutil.which('gh') or 'not found'}")
    return 0


def _codex_doctor(_: argparse.Namespace) -> int:
    candidate = shutil.which("codex.cmd") or shutil.which("codex")
    print("issue-proof codex doctor")
    print(f"- Codex CLI: {candidate or 'not found'}")
    if candidate:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                check=False,
                shell=False,
                timeout=5,
            )
            version = (result.stdout or result.stderr).decode("utf-8", errors="replace").strip()
        except (OSError, subprocess.SubprocessError):
            version = "unavailable"
        print(f"- Version: {version or 'unknown'}")
    print("- Task execution: not started by this doctor command")
    print("- Adapter: experimental-compatible JSONL import; no private Codex state is read")
    return 0


def _trace_markdown(summary) -> str:
    data = summary.as_dict(include_events=False)
    lines = [
        "# Codex Trace Summary",
        "",
        f"- Trace: `{data['trace_name']}`",
        f"- SHA-256: `{data['source_trace_sha256']}`",
        f"- Adapter: `{data['adapter_status']}`",
        f"- Lines: `{data['lines_seen']}`; valid events: `{data['valid_events']}`",
        f"- Unknown events: `{data['unknown_events']}`",
        f"- Parse errors: `{len(data['parse_errors'])}`",
        "",
        "## Commands",
        "",
    ]
    if data["command_evidence"]:
        lines.extend(
            f"- `{command.get('id')}` `{command.get('display_command') or '<unknown>'}` "
            f"-> exit `{command.get('exit_code')}`"
            for command in data["command_evidence"]
        )
    else:
        lines.append("- None")
    lines.extend(["", "## File changes", ""])
    if data["file_changes"]:
        lines.extend(
            f"- `{item.get('path')}` ({item.get('operation')})" for item in data["file_changes"]
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


def _receipt_issue(args: argparse.Namespace) -> dict[str, object] | None:
    issue_url = getattr(args, "issue_url", None)
    issue_file = getattr(args, "issue_file", None)
    if issue_url and issue_file:
        raise IssueProofError("--issue-url and --issue-file are mutually exclusive", exit_code=2)
    if issue_url:
        try:
            canonical = parse_issue_url(issue_url)
        except ValueError as exc:
            raise IssueProofError(str(exc), exit_code=2) from exc
        return {"source": "github-url", "url": canonical}
    if issue_file:
        body, _ = read_issue_file(issue_file)
        lines = body.splitlines()
        title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), "")
        if not title:
            title = next((line.strip() for line in lines if line.strip()), "Untitled issue")[:160]
        issue, _ = issue_info_from_payload(
            "local-file", str(issue_file.resolve()), body, title, None
        )
        return issue.as_dict()
    return None


def _load_claims(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    from .codex.claims import load_claim_inputs

    return load_claim_inputs(path)


def _codex_ingest(args: argparse.Namespace) -> int:
    from .codex.parser import parse_trace

    summary = parse_trace(
        args.trace,
        strict=args.strict,
        limits=_trace_limits(args),
    )
    root = ensure_output_dir(args.output)
    json_path = safe_output_file(root, "trace-summary.json")
    markdown_path = safe_output_file(root, "trace-summary.md")
    json_path.write_text(
        json.dumps(summary.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown_path.write_text(_trace_markdown(summary), encoding="utf-8", newline="\n")
    print(f"trace-summary: {json_path}")
    print(f"markdown: {markdown_path}")
    print(
        f"events: {summary.valid_events}; unknown: {summary.unknown_events}; "
        f"parse-errors: {len(summary.parse_errors)}"
    )
    return 0


def _codex_receipt(args: argparse.Namespace) -> int:
    from .codex.agents import collect_agents
    from .codex.parser import parse_trace
    from .codex.receipt import build_receipt, write_receipt_files

    summary = parse_trace(
        args.trace,
        strict=args.strict,
        include_messages=args.include_messages,
        limits=_trace_limits(args),
    )
    repo_root = args.repo_root.resolve()
    agents = collect_agents(
        repo_root,
        args.agents_target,
        include_content=args.include_agents_content,
    )
    receipt = build_receipt(
        summary,
        repo_root=repo_root,
        issue=_receipt_issue(args),
        baseline=load_report(args.baseline) if args.baseline else None,
        agents=agents,
        claim_inputs=_load_claims(args.claims),
        include_heuristics=args.heuristic_claims,
    )
    json_path, markdown_path = write_receipt_files(receipt, args.output)
    print(f"receipt: {json_path}")
    print(f"markdown: {markdown_path}")
    print(f"verdict: {receipt.verdict}")
    return 0


def _load_command_argv(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IssueProofError(f"could not read --command-argv JSON: {exc}", exit_code=2) from exc
    if isinstance(data, dict):
        data = data.get("argv")
    if (
        not isinstance(data, list)
        or not data
        or not all(isinstance(item, str) and item for item in data)
    ):
        raise IssueProofError(
            "--command-argv must contain a non-empty JSON string array", exit_code=2
        )
    return list(data)


def _codex_verify(args: argparse.Namespace) -> int:
    from .codex.agents import collect_agents
    from .codex.parser import parse_trace
    from .codex.receipt import build_receipt, write_receipt_files
    from .collector import _execution_info
    from .executor import execute_argv

    baseline = load_report(args.baseline)
    repo_root = args.repo_root.resolve()
    argv = _load_command_argv(args.command_argv)
    limits = _limits(args)
    result = execute_argv(argv, cwd=repo_root, limits=limits)
    execution = _execution_info(result).as_dict()
    execution["id"] = "verification-command"
    execution["cwd"] = "."
    verification_report = verify_argv_against_baseline(
        baseline,
        argv=argv,
        execution=execution,
        repo_root=repo_root,
    )
    summary = parse_trace(
        args.trace,
        strict=args.strict,
        include_messages=args.include_messages,
        limits=_trace_limits(args),
    )
    agents = collect_agents(
        repo_root,
        args.agents_target,
        include_content=args.include_agents_content,
    )
    issue = (
        {"source": "github-url", "url": args.issue_url}
        if args.issue_url
        else baseline.issue.as_dict()
    )
    receipt = build_receipt(
        summary,
        repo_root=repo_root,
        issue=issue,
        baseline=baseline,
        verification=verification_report,
        verification_command=execution,
        agents=agents,
        claim_inputs=_load_claims(args.claims),
        include_heuristics=args.heuristic_claims,
    )
    json_path, markdown_path = write_receipt_files(receipt, args.output)
    print(f"receipt: {json_path}")
    print(f"markdown: {markdown_path}")
    print(f"verification: {verification_report['verification']['outcome']}")
    print(f"verdict: {receipt.verdict}")
    return 5 if result.timed_out else 0


def _codex_agents(args: argparse.Namespace) -> int:
    from .codex.agents import collect_agents

    scan = collect_agents(args.repo, args.target, include_content=args.include_content)
    sys.stdout.write(json.dumps(scan.as_dict(), ensure_ascii=False, indent=2) + "\n")
    return 0


def _collect(args: argparse.Namespace) -> int:
    limits = _limits(args)
    repo_root = args.repo_root.resolve()
    if args.issue_file:
        report, json_path, markdown_path = collect_from_issue_file(
            issue_file=args.issue_file,
            repo_root=repo_root,
            command=args.command,
            output_dir=args.output,
            limits=limits,
        )
    else:
        try:
            canonical = parse_issue_url(args.issue_url)
        except ValueError as exc:
            raise IssueProofError(str(exc), exit_code=2) from exc
        payload = fetch_issue_via_gh(canonical, cwd=str(repo_root))
        issue, snapshot = issue_info_from_payload(
            "github-url",
            payload.url or canonical,
            payload.body,
            payload.title,
            payload.url or canonical,
        )
        from .collector import collect_evidence

        report, json_path, markdown_path = collect_evidence(
            issue=issue,
            issue_snapshot=snapshot,
            repo_root=repo_root,
            command=args.command,
            output_dir=args.output,
            limits=limits,
        )
    print(f"report: {json_path}")
    print(f"markdown: {markdown_path}")
    print(f"reproduction: {report.reproduction['outcome']}")
    return 5 if report.execution.timed_out else 0


def _verify(args: argparse.Namespace) -> int:
    baseline = load_report(args.baseline)
    report = verify_against_baseline(
        baseline,
        command=args.command,
        repo_root=args.repo_root.resolve(),
        limits=_limits(args),
    )
    json_path, markdown_path = write_report_files(report, args.output)
    print(f"report: {json_path}")
    print(f"markdown: {markdown_path}")
    print(f"verification: {report.verification['outcome']}")
    return 5 if report.execution.timed_out else 0


def _validate(args: argparse.Namespace) -> int:
    report = load_report(args.report)
    print(f"valid: {args.report} (schema {report.schema_version})")
    return 0


def _render(args: argparse.Namespace) -> int:
    report = load_report(args.report)
    markdown = render_report(report)
    if args.output:
        parent = ensure_output_dir(args.output.parent)
        target = safe_output_file(parent, args.output.name)
        target.write_text(markdown, encoding="utf-8", newline="\n")
        print(f"rendered: {target}")
    else:
        sys.stdout.write(markdown)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except IssueProofError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
