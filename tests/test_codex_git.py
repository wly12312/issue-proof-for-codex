import subprocess

from issue_proof.codex import git_provenance
from issue_proof.codex.git_provenance import (
    MAX_CHANGED_FILE_PATH_BYTES,
    MAX_CHANGED_FILES,
    _changed_files,
    collect_git_provenance,
    collect_git_state,
)


def test_git_provenance_is_best_effort_and_tracks_changed_files(tmp_path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "changed file.txt").write_text("change", encoding="utf-8")
    provenance = collect_git_provenance(tmp_path)
    assert provenance.repository_root == "."
    assert "changed file.txt" in provenance.end.changed_files
    assert provenance.end.dirty is True
    assert provenance.end.changed_files_total == 1
    assert provenance.end.changed_files_recorded == 1
    assert provenance.end.changed_files_truncated is False
    assert len(provenance.end.changed_files_sha256) == 64
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


def test_changed_files_are_bounded_but_digest_the_complete_normalized_set(
    tmp_path, monkeypatch
) -> None:
    paths = [f"src/file-{index:04d}.py" for index in range(MAX_CHANGED_FILES + 17)]
    status = "\n".join(f"?? {path}" for path in paths)

    def fake_git(args, cwd):
        if args[0] == "status":
            return 0, status, ""
        return 1, "", "not needed"

    monkeypatch.setattr(git_provenance, "_git", fake_git)
    state, warnings = collect_git_state(tmp_path)

    assert state.changed_files_total == len(paths)
    assert state.changed_files_recorded == MAX_CHANGED_FILES
    assert len(state.changed_files) == MAX_CHANGED_FILES
    assert state.changed_files_truncated is True
    assert state.changed_files_overflow is True
    assert state.changed_files_path_overflow is False
    assert state.changed_files_sha256 == git_provenance._digest_changed_files(sorted(paths))
    assert any("exceeded the entry limit" in warning for warning in warnings)
    assert all("file-" not in warning for warning in warnings)


def test_changed_file_path_length_is_bounded_without_leaking_the_path(
    tmp_path, monkeypatch
) -> None:
    long_path = "nested/" + ("长" * MAX_CHANGED_FILE_PATH_BYTES)
    status = f"?? {long_path}"

    def fake_git(args, cwd):
        if args[0] == "status":
            return 0, status, ""
        return 1, "", "not needed"

    monkeypatch.setattr(git_provenance, "_git", fake_git)
    state, warnings = collect_git_state(tmp_path)

    assert state.changed_files_total == 1
    assert state.changed_files_recorded == 0
    assert state.changed_files == []
    assert state.changed_files_truncated is True
    assert state.changed_files_overflow is False
    assert state.changed_files_path_overflow is True
    assert state.changed_files_sha256 == git_provenance._digest_changed_files([long_path])
    assert any("per-path byte limit" in warning for warning in warnings)
    assert long_path not in "\n".join(warnings)


def test_changed_file_digest_is_stable_for_unicode_paths(tmp_path, monkeypatch) -> None:
    paths = ["docs/变更说明.md", "src/café.py", "tests/路径/test.py"]
    status = "\n".join(f"?? {path}" for path in paths)

    def fake_git(args, cwd):
        if args[0] == "status":
            return 0, status, ""
        return 1, "", "not needed"

    monkeypatch.setattr(git_provenance, "_git", fake_git)
    first, _ = _changed_files(tmp_path)
    second, _ = _changed_files(tmp_path)

    assert first is not None and second is not None
    assert first.files == sorted(paths)
    assert first.sha256 == second.sha256
    assert first.sha256 == git_provenance._digest_changed_files(sorted(paths))
