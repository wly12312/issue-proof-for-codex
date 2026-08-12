import sys
from pathlib import Path

import pytest

from issue_proof.errors import CommandParseError
from issue_proof.executor import ExecutionLimits, execute_argv, parse_command


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def test_parse_command_rejects_shell_syntax() -> None:
    for command in ("echo hi | more", "echo hi && whoami", "echo `whoami`", "echo hi > out.txt"):
        with pytest.raises(CommandParseError):
            parse_command(command)


def test_parse_command_supports_quoted_windows_path() -> None:
    argv = parse_command(r'python "C:\Program Files\Example\bug.py" --flag')
    assert argv == ["python", r"C:\Program Files\Example\bug.py", "--flag"]


def test_execute_captures_and_redacts_output(tmp_path) -> None:
    result = execute_argv(
        parse_command(python_command("print('token=super-secret'); print('x' * 10000)")),
        cwd=tmp_path,
        limits=ExecutionLimits(timeout_seconds=5, max_output_bytes=100),
    )
    assert result.exit_code == 0
    assert result.stdout.truncated is True
    assert result.stdout.redacted is True
    assert "super-secret" not in result.stdout.summary
    assert len(result.stdout.sha256) == 64


def test_execute_marks_timeout(tmp_path) -> None:
    result = execute_argv(
        parse_command(python_command("import time; time.sleep(2)")),
        cwd=tmp_path,
        limits=ExecutionLimits(timeout_seconds=0.1, max_output_bytes=1000),
    )
    assert result.timed_out is True
    assert result.exit_code is None


def test_empty_command_is_rejected() -> None:
    with pytest.raises(CommandParseError):
        parse_command(" ")


def test_file_limit_is_validated() -> None:
    with pytest.raises(CommandParseError):
        execute_argv(
            [sys.executable, "-c", "pass"],
            cwd=Path.cwd(),
            limits=ExecutionLimits(max_files=0),
        )
