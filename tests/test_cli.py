import subprocess
import sys

import pytest

from issue_proof.cli import _load_command_argv, main
from issue_proof.errors import IssueProofError


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def test_cli_collect_validate_render_verify(tmp_path, capsys) -> None:
    issue = tmp_path / "issue.md"
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "issue-proof@example.invalid"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "IssueProof Test"],
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "https://github.com/example/cli-fixture.git",
        ],
        check=True,
        capture_output=True,
    )
    issue.write_text("# CLI issue\n\nA deterministic failure.\n", encoding="utf-8")
    baseline_dir = tmp_path / "baseline"
    command = python_command(
        "import pathlib,sys; sys.exit(1 if not pathlib.Path('fixed.marker').exists() else 0)"
    )
    assert (
        main(
            [
                "collect",
                "--issue-file",
                str(issue),
                "--command",
                command,
                "--output",
                str(baseline_dir),
                "--repo-root",
                str(tmp_path),
                "--identity-mode",
                "github",
            ]
        )
        == 0
    )
    baseline = baseline_dir / "report.json"
    assert main(["validate", str(baseline)]) == 0
    assert main(["render", str(baseline)]) == 0
    (tmp_path / "fixed.marker").write_text("fixed", encoding="utf-8")
    fixed_dir = tmp_path / "fixed"
    assert (
        main(
            [
                "verify",
                "--baseline",
                str(baseline),
                "--command",
                command,
                "--output",
                str(fixed_dir),
                "--repo-root",
                str(tmp_path),
                "--identity-mode",
                "github",
            ]
        )
        == 0
    )
    assert "verification: verified" in capsys.readouterr().out


def test_cli_bad_command_has_usage_exit_code(tmp_path) -> None:
    issue = tmp_path / "issue.md"
    issue.write_text("# Issue\n", encoding="utf-8")
    assert (
        main(
            [
                "collect",
                "--issue-file",
                str(issue),
                "--command",
                "echo hi | more",
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 2
    )


def test_command_argv_json_rejects_nul(tmp_path) -> None:
    command = tmp_path / "command-argv.json"
    command.write_text('{"argv":["bad\\u0000executable"]}', encoding="utf-8")

    with pytest.raises(IssueProofError, match="NUL"):
        _load_command_argv(command)


def test_doctor_help_path(capsys) -> None:
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "issue-proof doctor" in output
    assert "Support: Windows 10/11" in output
    assert "Tested Python: 3.11, 3.12, 3.14" in output
    assert "Linux/macOS: unsupported, untested, and unverified" in output
