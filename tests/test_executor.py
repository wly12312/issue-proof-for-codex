import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from issue_proof.errors import CommandParseError
from issue_proof.executor import (
    ExecutionLimits,
    _terminate_process_tree,
    execute_argv,
    parse_command,
)


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def test_parse_command_rejects_shell_syntax() -> None:
    for command in ("echo hi | more", "echo hi && whoami", "echo `whoami`", "echo hi > out.txt"):
        with pytest.raises(CommandParseError):
            parse_command(command)


def test_parse_command_supports_quoted_windows_path() -> None:
    argv = parse_command(r'python "C:\Program Files\Example\bug.py" --flag')
    assert argv == ["python", r"C:\Program Files\Example\bug.py", "--flag"]


def test_parse_command_preserves_explicit_empty_arguments() -> None:
    assert parse_command('tool "" tail') == ["tool", "", "tail"]


def test_parse_command_preserves_unicode_argument() -> None:
    assert parse_command('tool "中文 路径/café.txt"') == ["tool", "中文 路径/café.txt"]


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


@pytest.mark.skipif(os.name != "nt", reason="Windows-only process-tree termination contract")
def test_windows_taskkill_failure_falls_back_to_parent_kill(monkeypatch) -> None:
    class FakeProcess:
        pid = 123
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    process = FakeProcess()
    monkeypatch.setattr(
        "issue_proof.executor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode=1),
    )

    _terminate_process_tree(process)

    assert process.killed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows-only process-tree termination contract")
def test_execute_timeout_terminates_spawned_child(tmp_path) -> None:
    probe = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        taskkill = subprocess.run(
            ["taskkill", "/PID", str(probe.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            shell=False,
            timeout=5,
        )
        if taskkill.returncode != 0:
            detail = (taskkill.stderr or taskkill.stdout).decode("utf-8", errors="replace").strip()
            pytest.skip(
                "Windows denied taskkill /T /F permission; process-tree behavior was not tested: "
                f"{detail or f'exit {taskkill.returncode}'}"
            )
    finally:
        if probe.poll() is None:
            probe.kill()
        probe.wait(timeout=5)

    child_marker = tmp_path / "child survived timeout.txt"
    code = (
        "import subprocess,sys,time; "
        'child_code="import pathlib,sys,time; time.sleep(2); '
        "pathlib.Path(sys.argv[1]).write_text('alive',encoding='ascii')\"; "
        "subprocess.Popen([sys.executable,'-c',child_code,sys.argv[1]]); "
        "time.sleep(60)"
    )
    result = execute_argv(
        [sys.executable, "-c", code, str(child_marker)],
        cwd=tmp_path,
        limits=ExecutionLimits(timeout_seconds=1, max_output_bytes=1000),
    )
    time.sleep(2)
    assert result.timed_out is True
    assert result.exit_code is None
    assert not child_marker.exists()


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
