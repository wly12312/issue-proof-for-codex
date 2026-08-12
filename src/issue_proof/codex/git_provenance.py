"""Small, read-only Git provenance snapshot for maintenance receipts."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..redact import redact_text, sha256_text


@dataclass
class GitState:
    head_sha: str | None
    branch: str | None
    dirty: bool | None
    changed_files: list[str] = field(default_factory=list)
    captured: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "head_sha": self.head_sha,
            "branch": self.branch,
            "dirty": self.dirty,
            "changed_files": self.changed_files,
            "captured": self.captured,
        }


@dataclass
class GitProvenance:
    repository_root: str
    remote_url: str | None
    worktree_path: str
    common_git_dir_sha256: str | None
    start: GitState
    end: GitState
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository_root": self.repository_root,
            "remote_url": self.remote_url,
            "worktree_path": self.worktree_path,
            "common_git_dir_sha256": self.common_git_dir_sha256,
            "start": self.start.as_dict(),
            "end": self.end.as_dict(),
            "changed_files": self.end.changed_files,
            "warnings": self.warnings,
        }


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            check=False,
            shell=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", exc.__class__.__name__
    return (
        result.returncode,
        result.stdout.decode("utf-8", errors="replace").strip(),
        result.stderr.decode("utf-8", errors="replace").strip(),
    )


def _changed_files(root: Path) -> tuple[list[str], str | None]:
    code, status, error = _git(["status", "--porcelain", "--untracked-files=all"], root)
    if code != 0:
        return [], error or "git status failed"
    files: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        value = line[3:].strip()
        if " -> " in value:
            value = value.rsplit(" -> ", 1)[1]
        if value.startswith('"') and value.endswith('"'):
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                parsed = value[1:-1]
            if isinstance(parsed, str):
                value = parsed
        value = value.replace("\\", "/")
        if value and value not in files:
            files.append(value)
    return sorted(files), None


def collect_git_state(root: Path) -> tuple[GitState, list[str]]:
    warnings: list[str] = []
    code, head, error = _git(["rev-parse", "HEAD"], root)
    if code != 0:
        head = None
        warnings.append("Git HEAD is unavailable (repository may have no commit)")
    code, branch, _ = _git(["branch", "--show-current"], root)
    if code != 0:
        branch = None
        warnings.append("Git branch is unavailable")
    elif not branch:
        branch = "(detached)"
    files, status_error = _changed_files(root)
    if status_error:
        warnings.append("Git dirty state is unavailable")
        return GitState(head, branch, None, [], False), warnings
    return GitState(head, branch, bool(files), files, True), warnings


def collect_git_provenance(repo_root: Path) -> GitProvenance:
    """Capture start/end state without modifying the worktree or reading Git internals."""

    root = repo_root.resolve()
    warnings: list[str] = []
    start, start_warnings = collect_git_state(root)
    warnings.extend(start_warnings)
    code, git_root, error = _git(["rev-parse", "--show-toplevel"], root)
    if code != 0 or not git_root:
        warnings.append("repository is not a Git worktree; Git provenance is partial")
        end = start
        return GitProvenance(".", None, ".", None, start, end, warnings)
    actual_root = Path(git_root).resolve()
    try:
        root_name = (
            "." if actual_root == root else str(actual_root.relative_to(root)).replace("\\", "/")
        )
    except ValueError:
        root_name = "."
    code, remote, _ = _git(["config", "--get", "remote.origin.url"], actual_root)
    if code != 0 or not remote:
        remote = None
    else:
        remote = redact_text(remote).text
    code, common_dir, _ = _git(["rev-parse", "--git-common-dir"], actual_root)
    common_digest = (
        sha256_text(str((actual_root / common_dir).resolve())) if code == 0 and common_dir else None
    )
    end, end_warnings = collect_git_state(actual_root)
    warnings.extend(end_warnings)
    return GitProvenance(
        repository_root=root_name,
        remote_url=remote,
        worktree_path=".",
        common_git_dir_sha256=common_digest,
        start=start,
        end=end,
        warnings=warnings,
    )
