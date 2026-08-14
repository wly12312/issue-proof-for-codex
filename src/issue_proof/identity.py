"""Machine-comparable identities for commands, paths, repositories, and reports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .redact import sha256_bytes, sha256_text


def canonical_argv(argv: list[str]) -> str:
    """Serialize argv without shell parsing or redaction."""

    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) for item in argv)
        or not argv[0]
        or any("\x00" in item for item in argv)
    ):
        raise ValueError("argv must be a non-empty JSON string array without NUL bytes")
    return json.dumps(argv, ensure_ascii=False, separators=(",", ":"))


def argv_identity(argv: list[str]) -> str:
    return sha256_text(canonical_argv(argv))


def canonical_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve(strict=False)
    return os.path.normcase(str(resolved)).replace("/", "\\")


def path_identity(path: str | Path) -> str:
    return sha256_text(canonical_path(path))


def cwd_identity(path: str | Path) -> str:
    return path_identity(path)


def repository_identity(root: str | Path, remote_url: str | None = None) -> str:
    payload = {
        "root": canonical_path(root),
        "remote_url": remote_url or None,
    }
    return sha256_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def timeout_policy_identity(
    timeout_seconds: float | None,
    termination_policy: str | None,
    capture_limits: dict[str, Any] | None,
) -> str | None:
    if timeout_seconds is None and termination_policy is None and capture_limits is None:
        return None
    payload = {
        "timeout_seconds": timeout_seconds,
        "termination_policy": termination_policy,
        "capture_limits": capture_limits or {},
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def runtime_identity(runtime: dict[str, Any]) -> str:
    return sha256_text(
        json.dumps(runtime, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def tool_identity(tool_version: str | None) -> str | None:
    if tool_version is None:
        return None
    return sha256_text(tool_version)


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
