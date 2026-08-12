"""Best-effort provenance for repository-scoped AGENTS.md instructions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import DependencyError, OutputPathError
from ..redact import redact_text

_ABSOLUTE_WINDOWS = re.compile(r"^(?:[A-Za-z]:|[\\/])")
AGENT_FILENAMES = ("AGENTS.override.md", "AGENTS.md")


@dataclass
class AgentScan:
    repo_root: str
    target: str
    target_exists: bool
    scope_model: str = "codex-project-path-best-effort"
    files: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    include_content: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "target": self.target,
            "target_exists": self.target_exists,
            "scope_model": self.scope_model,
            "files": self.files,
            "warnings": self.warnings,
            "include_content": self.include_content,
        }


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/") or "."


def _safe_target(root: Path, target: str | Path) -> tuple[Path, str, bool]:
    raw = Path(target)
    if raw.is_absolute() or _ABSOLUTE_WINDOWS.match(str(target)):
        candidate = raw
    else:
        candidate = root / raw
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise OutputPathError(f"AGENTS target must stay inside repository: {target}") from exc
    exists = candidate.exists()
    if exists and candidate.is_symlink():
        raise OutputPathError(f"AGENTS target symlink is not followed: {target}")
    if exists and not candidate.is_file() and not candidate.is_dir():
        raise DependencyError(f"AGENTS target is not a regular file or directory: {target}")
    scope_dir = resolved if candidate.is_dir() else resolved.parent
    return scope_dir, _relative(root, resolved if exists else candidate), exists


def _file_record(
    root: Path,
    path: Path,
    scope_dir: Path,
    *,
    include_content: bool,
    max_content_bytes: int,
    warnings: list[str],
) -> dict[str, Any]:
    relative_path = _relative(root, path)
    relative_scope = _relative(root, scope_dir)
    scope = "repository" if relative_scope == "." else f"directory:{relative_scope}"
    record: dict[str, Any] = {
        "relative_path": relative_path,
        "scope": scope,
        "readable": False,
        "size_bytes": None,
        "sha256": None,
        "hash_complete": False,
        "symlink": path.is_symlink(),
    }
    if record["symlink"]:
        warnings.append(f"skipped symlinked instruction file: {relative_path}")
        record["warning"] = "symlink not followed"
        return record
    try:
        size = path.stat(follow_symlinks=False).st_size
        record["size_bytes"] = size
    except OSError as exc:
        warnings.append(
            f"could not stat instruction file {relative_path}: {exc.__class__.__name__}"
        )
        record["warning"] = "stat failed"
        return record
    digest = hashlib.sha256()
    content = bytearray()
    read_total = 0
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                read_total += len(chunk)
                if len(content) < max_content_bytes:
                    content.extend(chunk[: max_content_bytes - len(content)])
        record["readable"] = True
        record["sha256"] = digest.hexdigest()
        record["hash_complete"] = read_total == size
    except OSError as exc:
        warnings.append(
            f"could not read instruction file {relative_path}: {exc.__class__.__name__}"
        )
        record["warning"] = "read failed"
        if read_total:
            record["sha256"] = digest.hexdigest()
            record["hash_complete"] = False
        return record

    if size > max_content_bytes:
        record["content_truncated"] = True
        warnings.append(f"instruction content truncated for {relative_path}")
    else:
        record["content_truncated"] = False
    if include_content:
        text = bytes(content).decode("utf-8", errors="replace")
        text = "".join(char if char in "\t\n\r" or ord(char) >= 32 else "�" for char in text)
        clean = redact_text(text)
        record["content"] = clean.text
        record["content_redacted"] = clean.redacted
        if clean.redacted:
            warnings.append(f"instruction content redacted for {relative_path}")
        if "�" in text:
            record["encoding"] = "utf-8-with-replacement"
            warnings.append(f"instruction file was not valid UTF-8: {relative_path}")
        else:
            record["encoding"] = "utf-8"
    else:
        record["content"] = None
    return record


def collect_agents(
    repo_root: Path,
    target: str | Path = ".",
    *,
    include_content: bool = False,
    max_content_bytes: int = 32 * 1024,
) -> AgentScan:
    """Inspect only repository-path instruction files, never Codex home or private history."""

    if max_content_bytes <= 0:
        raise OutputPathError("AGENTS content limit must be greater than zero")
    try:
        root = repo_root.resolve()
    except OSError as exc:
        raise DependencyError(f"could not resolve repository root {repo_root}: {exc}") from exc
    if not root.exists() or not root.is_dir():
        raise DependencyError(f"repository root does not exist or is not a directory: {repo_root}")
    scope_dir, target_name, target_exists = _safe_target(root, target)
    scan = AgentScan(
        repo_root=".",
        target=target_name,
        target_exists=target_exists,
        include_content=include_content,
    )
    directories: list[Path] = []
    current = scope_dir
    while True:
        directories.append(current)
        if current == root:
            break
        if current.parent == current:
            scan.warnings.append("repository path did not reach the resolved root")
            break
        current = current.parent
    for directory in reversed(directories):
        selected: Path | None = None
        for filename in AGENT_FILENAMES:
            candidate = directory / filename
            if candidate.exists() or candidate.is_symlink():
                selected = candidate
                break
        if selected is None:
            continue
        scan.files.append(
            _file_record(
                root,
                selected,
                directory,
                include_content=include_content,
                max_content_bytes=max_content_bytes,
                warnings=scan.warnings,
            )
        )
    if not scan.files:
        scan.warnings.append("no repository-scoped AGENTS.md or AGENTS.override.md found")
    return scan
