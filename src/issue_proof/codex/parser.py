"""Streaming and privacy-preserving adapter for Codex JSONL traces."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import DependencyError, TraceParseError
from ..redact import redact_text, sha256_text
from .events import TraceEvent, TraceSummary


@dataclass(frozen=True)
class ParseLimits:
    """Memory and work limits for explicit trace imports."""

    max_line_bytes: int = 1_000_000
    max_text_bytes: int = 16_384
    max_events: int = 50_000


_ABSOLUTE_WINDOWS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_EVENT_KINDS = {
    "thread.started": "session",
    "session.started": "session",
    "turn.started": "turn",
    "turn.completed": "turn",
    "turn.failed": "turn",
    "command_execution": "command",
    "command_execution_output": "command",
    "command.exec": "command",
    "tool.command": "command",
    "file_change": "file_change",
    "file_changed": "file_change",
    "file_change_output": "file_change",
    "agent_message": "message",
    "assistant_message": "message",
    "final_message": "message",
    "message": "message",
    "tool_call": "tool_call",
    "function_call": "tool_call",
    "mcp_tool_call": "tool_call",
    "error": "error",
}


def _iter_bounded_lines(
    stream, max_line_bytes: int, digest: hashlib._Hash
) -> Iterator[tuple[bytes, bool]]:
    """Yield bounded lines without retaining an unbounded JSONL line in memory."""

    line = bytearray()
    too_large = False
    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        start = 0
        while start < len(chunk):
            newline = chunk.find(b"\n", start)
            end = len(chunk) if newline < 0 else newline
            piece = chunk[start:end]
            if not too_large:
                remaining = max_line_bytes - len(line)
                if remaining > 0:
                    line.extend(piece[:remaining])
                if len(piece) > max(0, remaining):
                    too_large = True
            if newline < 0:
                start = len(chunk)
            else:
                yield bytes(line).rstrip(b"\r"), too_large
                line.clear()
                too_large = False
                start = newline + 1
    if line or too_large:
        yield bytes(line).rstrip(b"\r"), too_large


def _safe_text(value: Any, limit: int, redactions: list[str], label: str) -> tuple[str, bool]:
    if value is None:
        return "", False
    if isinstance(value, (dict, list)):
        try:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            value = repr(value)
    text = str(value)
    text = "".join(char if char in "\t\n\r" or ord(char) >= 32 else "�" for char in text).replace(
        "\r\n", "\n"
    )
    redacted = redact_text(text)
    if redacted.redacted:
        redactions.append(label)
    truncated = len(redacted.text.encode("utf-8")) > limit
    if truncated:
        encoded = redacted.text.encode("utf-8")[:limit]
        text = encoded.decode("utf-8", errors="ignore") + "\n[trace text truncated]"
    else:
        text = redacted.text
    return text, truncated


def _safe_path(value: Any, redactions: list[str]) -> str:
    text, _ = _safe_text(value, 1_024, redactions, "path")
    if not text:
        return ""
    if _ABSOLUTE_WINDOWS.match(text) or text.startswith("/"):
        parts = [part for part in re.split(r"[\\/]", text) if part]
        tail = "/".join(parts[-2:]) if parts else "path"
        return f"<absolute-path>/{tail}"
    return text.replace("\\", "/")


def _string_field(payload: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _number_field(payload: dict[str, Any], *names: str) -> int | float | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return value
    return None


def _event_parts(record: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    outer = record.get("type")
    outer_type = outer if isinstance(outer, str) else "unknown"
    item = record.get("item")
    if isinstance(item, dict):
        item_type = item.get("type")
        if isinstance(item_type, str):
            return outer_type, item_type, item
    return outer_type, outer_type, record


def _stream_projection(
    value: Any,
    *,
    limit: int,
    redactions: list[str],
    label: str,
    explicit_truncated: bool = False,
) -> dict[str, Any]:
    redaction_count = len(redactions)
    text, truncated = _safe_text(value, limit, redactions, label)
    return {
        "summary": text,
        "sha256": sha256_text(text),
        "captured_bytes": len(text.encode("utf-8")),
        "truncated": truncated or explicit_truncated,
        "redacted": len(redactions) > redaction_count,
    }


def _message_value(payload: dict[str, Any]) -> Any:
    for key in ("text", "message", "content", "output"):
        if key in payload:
            value = payload[key]
            if isinstance(value, list):
                parts = []
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    elif isinstance(item, str):
                        parts.append(item)
                return "\n".join(parts)
            return value
    return ""


def _record_version(summary: TraceSummary, payload: dict[str, Any]) -> None:
    version = _string_field(payload, "codex_version", "cli_version", "version")
    app_version = _string_field(payload, "app_version")
    if version and not summary.codex_cli_version:
        summary.codex_cli_version = version[:128]
    if app_version and not summary.codex_app_version:
        summary.codex_app_version = app_version[:128]


def _add_event(
    summary: TraceSummary,
    line_number: int,
    outer: str,
    item_type: str,
    kind: str,
    data: dict[str, Any],
    text: str,
) -> None:
    summary.valid_events += 1
    event_id = f"event-{summary.valid_events:06d}"
    summary.events.append(
        TraceEvent(
            event_id=event_id,
            line_number=line_number,
            event_type=outer if outer != item_type else item_type,
            kind=kind,
            summary=text,
            data=data,
        )
    )


def _handle_record(
    summary: TraceSummary,
    record: dict[str, Any],
    line_number: int,
    limits: ParseLimits,
) -> None:
    outer, item_type, payload = _event_parts(record)
    _record_version(summary, payload)
    kind = _EVENT_KINDS.get(item_type, _EVENT_KINDS.get(outer, "unknown"))
    redactions = summary.redactions

    if kind == "session":
        session = _string_field(payload, "thread_id", "session_id", "id")
        task = _string_field(payload, "task_id", "run_id")
        if session and not summary.session_id:
            summary.session_id = _safe_text(session, 256, redactions, "session id")[0]
        if task and not summary.task_id:
            summary.task_id = _safe_text(task, 256, redactions, "task id")[0]
        data = {"session_id": summary.session_id, "task_id": summary.task_id}
        _add_event(summary, line_number, outer, item_type, kind, data, "session metadata")
        return

    if kind == "turn":
        _add_event(summary, line_number, outer, item_type, kind, {}, "turn lifecycle event")
        return

    if kind == "command":
        command = _string_field(payload, "command", "display_command")
        argv_value = payload.get("argv")
        argv = []
        if isinstance(argv_value, list):
            argv = [_safe_text(item, 1_024, redactions, "argv")[0] for item in argv_value]
        if not command and argv:
            command = " ".join(argv)
        safe_command, _ = _safe_text(command or "", 4_096, redactions, "command")
        cwd = _safe_path(payload.get("cwd"), redactions)
        exit_code = _number_field(payload, "exit_code", "exitCode", "returncode")
        duration = _number_field(payload, "duration_ms", "duration_seconds", "duration")
        if "duration_ms" in payload and isinstance(duration, (int, float)):
            duration = round(float(duration) / 1000, 6)
        stdout_value = payload.get("stdout", payload.get("stdout_summary", ""))
        stderr_value = payload.get("stderr", payload.get("stderr_summary", ""))
        stdout = _stream_projection(
            stdout_value,
            limit=limits.max_text_bytes,
            redactions=redactions,
            label="stdout",
            explicit_truncated=payload.get("stdout_truncated", False) is True,
        )
        stderr = _stream_projection(
            stderr_value,
            limit=limits.max_text_bytes,
            redactions=redactions,
            label="stderr",
            explicit_truncated=payload.get("stderr_truncated", False) is True,
        )
        evidence = {
            "id": f"command-{len(summary.command_evidence) + 1:04d}",
            "event_id": f"event-{summary.valid_events + 1:06d}",
            "argv": argv,
            "display_command": safe_command,
            "cwd": cwd or None,
            "exit_code": int(exit_code)
            if isinstance(exit_code, float) and exit_code.is_integer()
            else exit_code,
            "duration_seconds": duration,
            "timed_out": bool(payload.get("timed_out", False) or payload.get("timeout", False)),
            "status": _safe_text(
                _string_field(payload, "status") or "unknown",
                128,
                redactions,
                "command status",
            )[0],
            "stdout": stdout,
            "stderr": stderr,
        }
        summary.command_evidence.append(evidence)
        text = f"command execution: {safe_command or '<unknown>'}"
        if exit_code is not None:
            text += f" (exit {exit_code})"
        _add_event(
            summary, line_number, outer, item_type, kind, {"evidence_id": evidence["id"]}, text
        )
        return

    if kind == "tool_call":
        name = _string_field(payload, "name", "tool", "function") or "<unknown-tool>"
        call_id = _string_field(payload, "call_id", "id")
        args = payload.get("arguments", payload.get("args", payload.get("input")))
        args_text, _ = _safe_text(args, limits.max_text_bytes, redactions, "tool arguments")
        evidence = {
            "id": f"tool-{len(summary.tool_calls) + 1:04d}",
            "event_id": f"event-{summary.valid_events + 1:06d}",
            "name": _safe_text(name, 256, redactions, "tool name")[0],
            "call_id": (
                _safe_text(call_id, 256, redactions, "tool call id")[0] if call_id else None
            ),
            "arguments_sha256": sha256_text(args_text),
            "argument_keys": [
                _safe_text(key, 128, redactions, "tool argument key")[0]
                for key in sorted(args.keys(), key=str)[:32]
            ]
            if isinstance(args, dict)
            else [],
            "status": _safe_text(
                _string_field(payload, "status") or "unknown",
                128,
                redactions,
                "tool status",
            )[0],
        }
        summary.tool_calls.append(evidence)
        _add_event(
            summary,
            line_number,
            outer,
            item_type,
            kind,
            {"evidence_id": evidence["id"], "name": evidence["name"]},
            f"tool call: {evidence['name']}",
        )
        return

    if kind == "file_change":
        path = _safe_path(
            payload.get("path", payload.get("file_path", payload.get("filename"))), redactions
        )
        evidence = {
            "id": f"file-{len(summary.file_changes) + 1:04d}",
            "event_id": f"event-{summary.valid_events + 1:06d}",
            "path": path or "<unknown-path>",
            "operation": _safe_text(
                _string_field(payload, "operation", "change", "status") or "unknown",
                128,
                redactions,
                "file operation",
            )[0],
            "before_sha256": _safe_text(
                _string_field(payload, "before_sha256", "old_sha256"),
                128,
                redactions,
                "file hash",
            )[0]
            or None,
            "after_sha256": _safe_text(
                _string_field(payload, "after_sha256", "new_sha256"),
                128,
                redactions,
                "file hash",
            )[0]
            or None,
        }
        summary.file_changes.append(evidence)
        _add_event(
            summary,
            line_number,
            outer,
            item_type,
            kind,
            {"evidence_id": evidence["id"], "path": evidence["path"]},
            f"file change: {evidence['path']}",
        )
        return

    if kind == "message":
        message = _message_value(payload)
        safe_message, truncated = _safe_text(
            message, limits.max_text_bytes, redactions, "assistant message"
        )
        message_record: dict[str, Any] = {
            "id": f"message-{len(summary.final_messages) + 1:04d}",
            "event_id": f"event-{summary.valid_events + 1:06d}",
            "sha256": sha256_text(safe_message),
            "bytes": len(safe_message.encode("utf-8")),
            "truncated": truncated,
        }
        if summary.include_messages:
            message_record["text"] = safe_message
        else:
            summary.warnings.append(
                "assistant message content omitted by default; use --include-messages only "
                "with a privacy review"
            )
        summary.final_messages.append(message_record)
        _add_event(
            summary,
            line_number,
            outer,
            item_type,
            kind,
            {"evidence_id": message_record["id"], "content_included": summary.include_messages},
            "assistant message (content omitted)"
            if not summary.include_messages
            else "assistant message (sanitized)",
        )
        return

    if kind == "error":
        error_text, _ = _safe_text(
            payload.get("message", payload.get("error", "event error")),
            limits.max_text_bytes,
            redactions,
            "event error",
        )
        summary.warnings.append(f"trace reported an error event: {error_text[:256]}")
        _add_event(summary, line_number, outer, item_type, kind, {}, "Codex error event")
        return

    summary.unknown_events += 1
    if item_type not in summary.unknown_event_types:
        summary.unknown_event_types.append(item_type[:128])
    keys = [
        _safe_text(str(key), 128, redactions, "unknown event key")[0]
        for key in sorted(payload.keys(), key=str)[:32]
    ]
    _add_event(
        summary,
        line_number,
        outer,
        item_type,
        "unknown",
        {"keys": keys},
        f"unknown event type: {item_type[:128]}",
    )


def parse_trace(
    path: Path,
    *,
    strict: bool = False,
    include_messages: bool = False,
    limits: ParseLimits | None = None,
) -> TraceSummary:
    """Read one explicitly supplied JSONL file without loading the trace into memory."""

    selected = limits or ParseLimits()
    if selected.max_line_bytes <= 0 or selected.max_text_bytes <= 0 or selected.max_events <= 0:
        raise TraceParseError("trace parser limits must be greater than zero")
    if not path.exists() or not path.is_file():
        raise DependencyError(f"trace does not exist or is not a file: {path}")

    digest = hashlib.sha256()
    summary = TraceSummary(
        trace_name=path.name,
        source_trace_sha256="0" * 64,
        include_messages=include_messages,
    )
    try:
        stream = path.open("rb")
    except OSError as exc:
        raise DependencyError(f"could not read trace {path}: {exc}") from exc
    with stream:
        for line_number, (raw_line, too_large) in enumerate(
            _iter_bounded_lines(stream, selected.max_line_bytes, digest), start=1
        ):
            summary.lines_seen = line_number
            if not raw_line.strip():
                continue
            if too_large:
                error = {
                    "line": line_number,
                    "kind": "line-too-large",
                    "message": f"line exceeded {selected.max_line_bytes} bytes",
                }
                summary.parse_errors.append(error)
                summary.warnings.append(
                    f"trace line {line_number} exceeded the configured size limit"
                )
                if strict:
                    summary.source_trace_sha256 = digest.hexdigest()
                    raise TraceParseError(error["message"])
                continue
            try:
                decoded = raw_line.decode("utf-8")
                record = json.loads(decoded)
            except UnicodeDecodeError as exc:
                error = {"line": line_number, "kind": "invalid-utf8", "message": "invalid UTF-8"}
                summary.parse_errors.append(error)
                summary.warnings.append(f"trace line {line_number} was not valid UTF-8")
                if strict:
                    summary.source_trace_sha256 = digest.hexdigest()
                    raise TraceParseError(error["message"]) from exc
                continue
            except json.JSONDecodeError as exc:
                error = {"line": line_number, "kind": "invalid-json", "message": "invalid JSON"}
                summary.parse_errors.append(error)
                summary.warnings.append(f"trace line {line_number} was not valid JSON")
                if strict:
                    summary.source_trace_sha256 = digest.hexdigest()
                    raise TraceParseError(error["message"]) from exc
                continue
            if not isinstance(record, dict):
                error = {
                    "line": line_number,
                    "kind": "non-object",
                    "message": "JSON root is not an object",
                }
                summary.parse_errors.append(error)
                summary.warnings.append(f"trace line {line_number} was not a JSON object")
                if strict:
                    summary.source_trace_sha256 = digest.hexdigest()
                    raise TraceParseError(error["message"])
                continue
            if summary.valid_events >= selected.max_events:
                if "event limit reached" not in summary.warnings:
                    summary.warnings.append(
                        f"trace event limit reached at {selected.max_events}; "
                        "later events were ignored"
                    )
                continue
            _handle_record(summary, record, line_number, selected)
    summary.source_trace_sha256 = digest.hexdigest()
    if summary.parse_errors:
        summary.warnings.append("trace contains parse errors; conclusions are downgraded")
    if summary.unknown_events:
        summary.warnings.append(
            f"trace contains {summary.unknown_events} unknown event type(s); "
            "only known projections were used"
        )
    if include_messages:
        summary.warnings.append(
            "privacy warning: --include-messages was requested; message text was still "
            "sanitized and bounded"
        )
    return summary
