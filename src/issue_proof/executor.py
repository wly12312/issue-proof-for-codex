"""Safe argv parsing and bounded, timeout-aware subprocess execution."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .errors import CommandParseError, DependencyError
from .redact import decode_and_redact, sha256_text


@dataclass(frozen=True)
class ExecutionLimits:
    timeout_seconds: float = 120.0
    max_output_bytes: int = 256_000
    max_files: int = 16


@dataclass(frozen=True)
class StreamResult:
    summary: str
    sha256: str
    captured_bytes: int
    truncated: bool
    redacted: bool


@dataclass(frozen=True)
class ExecutionResult:
    argv: list[str]
    display_command: str
    cwd: str
    started_at: str
    finished_at: str
    duration_seconds: float
    exit_code: int | None
    timed_out: bool
    stdout: StreamResult
    stderr: StreamResult


def _has_unquoted_shell_operator(command: str) -> str | None:
    quote: str | None = None
    escaped = False
    operators = set("|&;<>()`\n\r")
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in operators:
            return char
    if quote:
        return "unclosed quote"
    if escaped:
        return "trailing escape"
    return None


def parse_command(command: str) -> list[str]:
    """Parse a simple command line into argv and reject shell syntax."""

    if not command or not command.strip():
        raise CommandParseError("--command must not be empty")
    if "\x00" in command:
        raise CommandParseError("--command contains a NUL byte")
    operator = _has_unquoted_shell_operator(command)
    if operator:
        raise CommandParseError(
            f"--command contains shell syntax ({operator!r}); provide a simple argv-style command"
        )
    try:
        argv = _split_argv(command)
    except ValueError as exc:
        raise CommandParseError(f"cannot parse --command: {exc}") from exc
    if not argv:
        raise CommandParseError("--command produced no arguments")
    return argv


def _split_argv(command: str) -> list[str]:
    """Split quotes and whitespace while keeping Windows backslashes as path characters."""

    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and os.name != "nt":
            next_char = command[index + 1] if index + 1 < len(command) else ""
            if next_char in {'"', "'", "\\", " ", "\t", "\r", "\n"}:
                current.append(next_char)
                index += 2
                continue
            current.append(char)
            index += 1
            continue
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
        elif char in {'"', "'"}:
            quote = char
        elif char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
        index += 1
    if quote:
        raise ValueError("No closing quotation")
    if current:
        tokens.append("".join(current))
    return tokens


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bounded_reader(stream, limit: int, holder: dict[str, object]) -> None:
    chunks: list[bytes] = []
    captured = 0
    total = 0
    truncated = False
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if captured < limit:
            keep = chunk[: limit - captured]
            chunks.append(keep)
            captured += len(keep)
        if total > limit:
            truncated = True
    holder["raw"] = b"".join(chunks)
    holder["total"] = total
    holder["truncated"] = truncated


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=5,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
            time.sleep(0.1)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def _stream_result(holder: dict[str, object]) -> StreamResult:
    raw = holder.get("raw", b"")
    if not isinstance(raw, bytes):
        raw = b""
    redacted = decode_and_redact(raw)
    return StreamResult(
        summary=redacted.text,
        sha256=sha256_text(redacted.text),
        captured_bytes=int(holder.get("total", len(raw))),
        truncated=bool(holder.get("truncated", False)),
        redacted=redacted.redacted,
    )


def execute_argv(
    argv: list[str],
    *,
    cwd: Path,
    limits: ExecutionLimits | None = None,
    clock: Callable[[], str] = _iso_now,
) -> ExecutionResult:
    """Run argv with shell=False, bounded streams, and a process-tree timeout."""

    if not argv:
        raise CommandParseError("command argv must not be empty")
    if not cwd.exists() or not cwd.is_dir():
        raise DependencyError(f"command cwd does not exist or is not a directory: {cwd}")
    selected = limits or ExecutionLimits()
    if selected.timeout_seconds <= 0:
        raise CommandParseError("timeout must be greater than zero")
    if selected.max_output_bytes <= 0:
        raise CommandParseError("max output bytes must be greater than zero")
    if selected.max_files <= 0:
        raise CommandParseError("max files must be greater than zero")

    started = clock()
    start_monotonic = time.monotonic()
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    popen_kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "creationflags": creationflags,
    }
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(argv, **popen_kwargs)  # type: ignore[arg-type]
    except FileNotFoundError as exc:
        raise DependencyError(f"command executable not found: {argv[0]!r}") from exc
    except OSError as exc:
        raise DependencyError(f"could not start command {argv[0]!r}: {exc}") from exc

    stdout_holder: dict[str, object] = {}
    stderr_holder: dict[str, object] = {}
    stdout_thread = threading.Thread(
        target=_bounded_reader,
        args=(process.stdout, selected.max_output_bytes, stdout_holder),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_bounded_reader,
        args=(process.stderr, selected.max_output_bytes, stderr_holder),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        process.wait(timeout=selected.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        process.wait(timeout=5)
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    finished = clock()
    duration = round(max(0.0, time.monotonic() - start_monotonic), 6)
    return ExecutionResult(
        argv=list(argv),
        display_command=shlex.join(argv),
        cwd=str(cwd),
        started_at=started,
        finished_at=finished,
        duration_seconds=duration,
        exit_code=None if timed_out else process.returncode,
        timed_out=timed_out,
        stdout=_stream_result(stdout_holder),
        stderr=_stream_result(stderr_holder),
    )
