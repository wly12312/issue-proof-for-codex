import hashlib
import json
from pathlib import Path

import pytest

from issue_proof.codex.parser import ParseLimits, parse_trace
from issue_proof.codex.receipt import build_receipt
from issue_proof.errors import TraceParseError

FIXTURE_ROOT = Path(__file__).parents[1] / "examples" / "codex-maintenance"


@pytest.mark.parametrize("name", ["trace-order-a.jsonl", "trace-order-b.jsonl"])
def test_parser_accepts_two_event_orderings_and_hashes_source(name: str) -> None:
    path = FIXTURE_ROOT / name
    summary = parse_trace(path)
    assert summary.valid_events == 6
    assert summary.unknown_events == 0
    assert summary.source_trace_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert summary.command_evidence[0]["exit_code"] == 1
    assert summary.command_evidence[0]["stdout"]["redacted"] is (name.endswith("a.jsonl"))


def test_parser_ignores_unknown_events_and_keeps_only_key_metadata(tmp_path) -> None:
    trace = tmp_path / "unknown.jsonl"
    trace.write_text(
        json.dumps(
            {
                "type": "future.event",
                "secret": "sk-proj-do-not-persist",
                "nested": {"prompt": "unicode 你好"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = parse_trace(trace)
    assert summary.unknown_events == 1
    assert summary.unknown_event_types == ["future.event"]
    assert "secret" in summary.events[0].data["keys"]
    assert "sk-proj" not in json.dumps(summary.as_dict(), ensure_ascii=False)


def test_parser_handles_corrupt_and_huge_lines_leniently(tmp_path) -> None:
    trace = tmp_path / "bad.jsonl"
    trace.write_bytes(
        b"\n"
        + b"not-json\n"
        + (b'{"type":"future.event","payload":"' + b"x" * 4096 + b'"}\n')
        + b"{"
    )
    summary = parse_trace(trace, limits=ParseLimits(max_line_bytes=256, max_text_bytes=128))
    assert {item["kind"] for item in summary.parse_errors} == {"invalid-json", "line-too-large"}
    assert all(len(json.dumps(item)) < 256 for item in summary.parse_errors)


def test_parser_strict_mode_reports_corrupt_line(tmp_path) -> None:
    trace = tmp_path / "bad.jsonl"
    trace.write_text('{"type":"ok"}\nnot-json\n', encoding="utf-8")
    with pytest.raises(TraceParseError):
        parse_trace(trace, strict=True)


def test_parser_include_messages_is_explicit_and_bounded(tmp_path) -> None:
    trace = tmp_path / "message.jsonl"
    trace.write_text(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "token=sk-proj-secret 你好" + "x" * 2000,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary = parse_trace(
        trace,
        include_messages=True,
        limits=ParseLimits(max_text_bytes=128),
    )
    message = summary.final_messages[0]
    assert message["text"].startswith("token=[REDACTED]")
    assert len(message["text"].encode("utf-8")) < 256
    assert any("privacy warning" in warning for warning in summary.warnings)


MALICIOUS_JSON_LINES = [
    pytest.param(
        b'{"type":"command_execution","command":"\\ud800"}',
        id="orphan-surrogate",
    ),
    pytest.param(
        ('{"type":"command_execution","stdout":' + "[" * 1_500 + "0" + "]" * 1_500 + "}").encode(
            "ascii"
        ),
        id="deep-nesting",
    ),
    pytest.param(
        b'{"type":"command_execution","exit_code":' + b"9" * 5_000 + b"}",
        id="huge-integer",
    ),
    pytest.param(
        b'{"type":"command_execution","duration_seconds":NaN}',
        id="nan",
    ),
    pytest.param(
        b'{"type":"command_execution","duration_seconds":Infinity}',
        id="positive-infinity",
    ),
    pytest.param(
        b'{"type":"command_execution","duration_seconds":-Infinity}',
        id="negative-infinity",
    ),
    pytest.param(
        b'{"type":"command_execution","duration_seconds":1e309}',
        id="overflowing-float",
    ),
]


@pytest.mark.parametrize("malicious_line", MALICIOUS_JSON_LINES)
def test_parser_rejects_malicious_json_values_leniently(tmp_path, malicious_line: bytes) -> None:
    trace = tmp_path / "malicious.jsonl"
    trace.write_bytes(malicious_line + b'\n{"type":"turn.started"}\n')

    summary = parse_trace(trace)

    assert summary.valid_events == 1
    assert summary.command_evidence == []
    assert summary.parse_errors == [{"line": 1, "kind": "invalid-json", "message": "invalid JSON"}]
    assert build_receipt(summary).verdict == "inconclusive"
    json.dumps(summary.as_dict(), ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("malicious_line", MALICIOUS_JSON_LINES)
def test_parser_rejects_malicious_json_values_strictly(tmp_path, malicious_line: bytes) -> None:
    trace = tmp_path / "malicious.jsonl"
    trace.write_bytes(malicious_line + b"\n")

    with pytest.raises(TraceParseError):
        parse_trace(trace, strict=True)


@pytest.mark.parametrize(
    "numeric_fields",
    [
        pytest.param('"duration_seconds":-0.001', id="negative-duration"),
        pytest.param('"exit_code":true', id="boolean-exit-code"),
        pytest.param('"exit_code":1.0', id="float-exit-code"),
    ],
)
def test_parser_rejects_invalid_command_numbers(tmp_path, numeric_fields: str) -> None:
    trace = tmp_path / "invalid-command-number.jsonl"
    trace.write_text(
        f'{{"type":"command_execution","command":"verify",{numeric_fields}}}\n',
        encoding="utf-8",
    )

    summary = parse_trace(trace)

    assert summary.command_evidence == []
    assert summary.parse_errors == [
        {"line": 1, "kind": "invalid-record", "message": "invalid event record"}
    ]
    with pytest.raises(TraceParseError):
        parse_trace(trace, strict=True)


def test_parser_keeps_only_finite_nonnegative_durations_and_integer_exit_codes(tmp_path) -> None:
    trace = tmp_path / "valid-command-numbers.jsonl"
    trace.write_text(
        '{"type":"command_execution","duration_seconds":0.25,"exit_code":0}\n'
        '{"type":"command_execution","duration_ms":1500,"exit_code":-1}\n',
        encoding="utf-8",
    )

    summary = parse_trace(trace)

    assert [item["duration_seconds"] for item in summary.command_evidence] == [0.25, 1.5]
    assert [item["exit_code"] for item in summary.command_evidence] == [0, -1]
    assert all(type(item["exit_code"]) is int for item in summary.command_evidence)
    json.dumps(summary.as_dict(), allow_nan=False)
