import json
import subprocess
import sys
from pathlib import Path

from issue_proof.cli import main

FIXTURE = Path(__file__).parents[1] / "examples" / "codex-maintenance" / "trace-order-a.jsonl"


def test_codex_ingest_and_receipt_cli_are_offline(tmp_path, capsys) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    ingest = tmp_path / "ingest"
    assert (
        main(
            [
                "codex",
                "ingest",
                "--trace",
                str(FIXTURE),
                "--output",
                str(ingest),
            ]
        )
        == 0
    )
    summary = json.loads((ingest / "trace-summary.json").read_text(encoding="utf-8"))
    assert summary["source_trace_sha256"]
    receipt_path = tmp_path / "receipt.json"
    assert (
        main(
            [
                "codex",
                "receipt",
                "--trace",
                str(FIXTURE),
                "--repo-root",
                str(tmp_path),
                "--issue-url",
                "https://github.com/example/repo/issues/8",
                "--output",
                str(receipt_path),
            ]
        )
        == 0
    )
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert data["issue"]["number"] == 8
    assert (tmp_path / "receipt.md").exists()
    assert "verdict:" in capsys.readouterr().out


def test_codex_verify_cli_runs_same_explicit_argv_and_writes_receipt(tmp_path) -> None:
    issue = tmp_path / "issue.md"
    issue.write_text("# CLI Codex issue\n\nA deterministic failure.\n", encoding="utf-8")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    code = "import pathlib,sys; sys.exit(1 if not pathlib.Path('fixed.marker').exists() else 0)"
    command = f'"{sys.executable}" -c "{code}"'
    baseline_dir = tmp_path / "baseline"
    assert (
        main(
            [
                "collect",
                "--issue-file",
                str(issue),
                "--command",
                command,
                "--repo-root",
                str(tmp_path),
                "--output",
                str(baseline_dir),
            ]
        )
        == 0
    )
    (tmp_path / "fixed.marker").write_text("fixed", encoding="utf-8")
    argv_file = tmp_path / "command argv with spaces.json"
    argv_file.write_text(json.dumps({"argv": [sys.executable, "-c", code]}), encoding="utf-8")
    output = tmp_path / "verified"
    assert (
        main(
            [
                "codex",
                "verify",
                "--baseline",
                str(baseline_dir / "report.json"),
                "--trace",
                str(FIXTURE),
                "--command-argv",
                str(argv_file),
                "--repo-root",
                str(tmp_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    data = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert data["verification"]["outcome"] == "verified"
    assert data["verdict"] == "verified"
    assert data["verification"]["same_argv"] is True


def test_codex_agents_cli_is_read_only_json(tmp_path, capsys) -> None:
    (tmp_path / "AGENTS.md").write_text("Use pytest.\n", encoding="utf-8")
    assert main(["codex", "agents", "--repo", str(tmp_path), "--target", "missing.py"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target_exists"] is False
    assert data["files"][0]["relative_path"] == "AGENTS.md"
