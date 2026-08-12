"""Small, read-only Git provenance snapshot for maintenance receipts."""

from __future__ import annotations

import ast
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..redact import redact_text, sha256_text

MAX_CHANGED_FILES = 256
MAX_CHANGED_FILE_PATH_BYTES = 512
EMPTY_CHANGED_FILES_SHA256 = hashlib.sha256(b"").hexdigest()


@dataclass
class ChangedFilesCapture:
    """Bounded changed-file output with a digest over the complete normalized input."""

    files: list[str]
    total: int
    sha256: str
    overflow: bool = False
    path_overflow: bool = False

    @property
    def truncated(self) -> bool:
        return self.overflow or self.path_overflow


@dataclass
class GitState:
    head_sha: str | None
    branch: str | None
    dirty: bool | None
    changed_files: list[str] = field(default_factory=list)
    captured: bool = True
    changed_files_total: int = 0
    changed_files_recorded: int = 0
    changed_files_truncated: bool = False
    changed_files_overflow: bool = False
    changed_files_path_overflow: bool = False
    changed_files_sha256: str = EMPTY_CHANGED_FILES_SHA256
    changed_files_limit: int = MAX_CHANGED_FILES
    changed_file_path_max_bytes: int = MAX_CHANGED_FILE_PATH_BYTES

    def as_dict(self) -> dict[str, Any]:
        return {
            "head_sha": self.head_sha,
            "branch": self.branch,
            "dirty": self.dirty,
            "changed_files": self.changed_files,
            "captured": self.captured,
            "changed_files_total": self.changed_files_total,
            "changed_files_recorded": self.changed_files_recorded,
            "changed_files_truncated": self.changed_files_truncated,
            "changed_files_overflow": self.changed_files_overflow,
            "changed_files_path_overflow": self.changed_files_path_overflow,
            "changed_files_sha256": self.changed_files_sha256,
            "changed_files_limit": self.changed_files_limit,
            "changed_file_path_max_bytes": self.changed_file_path_max_bytes,
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
            "changed_files_total": self.end.changed_files_total,
            "changed_files_recorded": self.end.changed_files_recorded,
            "changed_files_truncated": self.end.changed_files_truncated,
            "changed_files_overflow": self.end.changed_files_overflow,
            "changed_files_path_overflow": self.end.changed_files_path_overflow,
            "changed_files_sha256": self.end.changed_files_sha256,
            "changed_files_limit": self.end.changed_files_limit,
            "changed_file_path_max_bytes": self.end.changed_file_path_max_bytes,
            "warnings": self.warnings,
        }


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        git_args = ["-c", "core.quotepath=false", *args] if args[:1] == ["status"] else args
        result = subprocess.run(
            ["git", *git_args],
            cwd=str(cwd),
            capture_output=True,
            check=False,
            shell=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", exc.__class__.__name__
    stdout = result.stdout.decode("utf-8", errors="replace")
    if args[:1] != ["status"]:
        stdout = stdout.strip()
    return result.returncode, stdout, result.stderr.decode("utf-8", errors="replace").strip()


def _digest_changed_files(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def _changed_files(root: Path) -> tuple[ChangedFilesCapture | None, str | None]:
    code, status, error = _git(["status", "--porcelain", "--untracked-files=all"], root)
    if code != 0:
        return None, error or "git status failed"
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
    normalized = sorted(set(files))
    digest = _digest_changed_files(normalized)
    path_overflow = False
    recorded: list[str] = []
    for path in normalized:
        if len(path.encode("utf-8", errors="replace")) > MAX_CHANGED_FILE_PATH_BYTES:
            path_overflow = True
            continue
        if len(recorded) >= MAX_CHANGED_FILES:
            break
        recorded.append(path)
    return (
        ChangedFilesCapture(
            files=recorded,
            total=len(normalized),
            sha256=digest,
            overflow=len(normalized) > MAX_CHANGED_FILES,
            path_overflow=path_overflow,
        ),
        None,
    )


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
    capture, status_error = _changed_files(root)
    if status_error or capture is None:
        warnings.append("Git dirty state is unavailable")
        return GitState(head, branch, None, [], False), warnings
    if capture.overflow:
        warnings.append(
            "Git changed-file provenance exceeded the entry limit; omitted paths are "
            "represented only by the total count and digest"
        )
    if capture.path_overflow:
        warnings.append(
            "Git changed-file provenance omitted paths over the per-path byte limit; "
            "omitted paths are represented only by the total count and digest"
        )
    return GitState(
        head_sha=head,
        branch=branch,
        dirty=bool(capture.total),
        changed_files=capture.files,
        captured=True,
        changed_files_total=capture.total,
        changed_files_recorded=len(capture.files),
        changed_files_truncated=capture.truncated,
        changed_files_overflow=capture.overflow,
        changed_files_path_overflow=capture.path_overflow,
        changed_files_sha256=capture.sha256,
    ), warnings


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
