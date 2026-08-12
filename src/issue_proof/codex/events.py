"""Conservative, serializable representations of Codex JSONL evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEvent:
    """A bounded event projection; the original JSON object is never retained."""

    event_id: str
    line_number: int
    event_type: str
    kind: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.event_id,
            "line": self.line_number,
            "type": self.event_type,
            "kind": self.kind,
            "summary": self.summary,
        }
        result.update(self.data)
        return result


@dataclass
class TraceSummary:
    """Result of streaming a trace once.

    The current Codex CLI documents JSONL and a small stable outer event vocabulary, but item
    payloads can evolve.  Fields in this object are therefore evidence projections, not claims
    that every historical or future Codex release has the same payload shape.
    """

    trace_name: str
    source_trace_sha256: str
    adapter_status: str = "experimental-compatible"
    lines_seen: int = 0
    valid_events: int = 0
    events: list[TraceEvent] = field(default_factory=list)
    command_evidence: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    file_changes: list[dict[str, Any]] = field(default_factory=list)
    final_messages: list[dict[str, Any]] = field(default_factory=list)
    session_id: str | None = None
    task_id: str | None = None
    codex_cli_version: str | None = None
    codex_app_version: str | None = None
    unknown_events: int = 0
    unknown_event_types: list[str] = field(default_factory=list)
    event_limit_reached: bool = False
    parse_errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    include_messages: bool = False

    def as_dict(self, *, include_events: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "trace_name": self.trace_name,
            "source_trace_sha256": self.source_trace_sha256,
            "adapter_status": self.adapter_status,
            "lines_seen": self.lines_seen,
            "valid_events": self.valid_events,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "codex_cli_version": self.codex_cli_version,
            "codex_app_version": self.codex_app_version,
            "unknown_events": self.unknown_events,
            "unknown_event_types": self.unknown_event_types,
            "event_limit_reached": self.event_limit_reached,
            "command_evidence": self.command_evidence,
            "tool_calls": self.tool_calls,
            "file_changes": self.file_changes,
            "final_messages": self.final_messages if self.include_messages else [],
            "parse_errors": self.parse_errors,
            "warnings": self.warnings,
            "redactions": self.redactions,
            "include_messages": self.include_messages,
        }
        if include_events:
            result["events"] = [event.as_dict() for event in self.events]
        return result
