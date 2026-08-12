import subprocess

from issue_proof.codex.git_provenance import collect_git_provenance


def test_git_provenance_is_best_effort_and_tracks_changed_files(tmp_path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "changed file.txt").write_text("change", encoding="utf-8")
    provenance = collect_git_provenance(tmp_path)
    assert provenance.repository_root == "."
    assert "changed file.txt" in provenance.end.changed_files
    assert provenance.end.dirty is True
    assert provenance.common_git_dir_sha256 is not None
    assert provenance.remote_url is None


def test_git_provenance_redacts_remote_credentials(tmp_path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "https://user:password@example.test/repo.git",
        ],
        check=True,
        capture_output=True,
    )
    provenance = collect_git_provenance(tmp_path)
    assert provenance.remote_url == "https://[REDACTED]@example.test/repo.git"
