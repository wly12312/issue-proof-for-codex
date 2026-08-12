import sys
from pathlib import Path

from issue_proof.collector import collect_from_issue_file
from issue_proof.models import validate_report_dict


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


def init_git_repo(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)


def test_local_issue_collects_complete_evidence_bundle(tmp_path) -> None:
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    init_git_repo(repo)
    issue_file = repo / "issue.md"
    issue_file.write_text("# Fixture bug\n\nFailure details.\n", encoding="utf-8")
    output = repo / ".issue-proof" / "run-001"
    report, json_path, markdown_path = collect_from_issue_file(
        issue_file=issue_file,
        repo_root=repo,
        command=python_command("import sys; print('failure'); sys.exit(1)"),
        output_dir=output,
    )
    assert json_path == output.resolve() / "report.json"
    assert markdown_path.exists()
    assert report.reproduction["outcome"] == "reproduced"
    assert report.execution.exit_code == 1
    assert report.artifacts[0]["path"] == "issue-source.md"
    validate_report_dict(report.as_dict())
    assert "failure" in markdown_path.read_text(encoding="utf-8")


def test_static_collection_is_not_run(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    issue = repo / "issue.md"
    issue.write_text("# Static\n", encoding="utf-8")
    report, _, _ = collect_from_issue_file(
        issue_file=issue, repo_root=repo, command=None, output_dir=repo / "out"
    )
    assert report.reproduction["outcome"] == "not-run"
    assert report.execution.argv == []


def test_invalid_utf8_is_reported(tmp_path) -> None:
    issue = tmp_path / "issue.md"
    issue.write_bytes(b"# Bad UTF-8\n\xff\n")
    report, _, _ = collect_from_issue_file(
        issue_file=issue, repo_root=tmp_path, command=None, output_dir=tmp_path / "out"
    )
    assert any("invalid UTF-8" in warning for warning in report.warnings)
    assert "\ufffd" in report.issue.body_excerpt


def test_redacted_repository_display_path_is_not_reused_as_command_cwd(tmp_path) -> None:
    repo = tmp_path / "token=super-secret" / "Unicode 空格 repo"
    repo.mkdir(parents=True)
    init_git_repo(repo)
    issue = repo / "issue.md"
    issue.write_text("# Path control boundary\n", encoding="utf-8")

    report, _, _ = collect_from_issue_file(
        issue_file=issue,
        repo_root=repo,
        command=python_command(
            "from pathlib import Path; print(Path.cwd().name == 'Unicode 空格 repo')"
        ),
        output_dir=repo / "out",
    )

    assert report.execution.exit_code == 0
    assert report.execution.stdout["summary"].strip() == "True"
    assert "super-secret" not in report.repository.root
