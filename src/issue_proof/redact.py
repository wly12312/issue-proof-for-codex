"""Conservative secret redaction for issue text and process output."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

REDACTION = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/@\s]+):(?P<password>[^/@\s]+)@"
)
_BEARER = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+")
_GITHUB_TOKEN = re.compile(r"\b(?:gh[pso]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b")
_OPENAI_KEY = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_AWS_SECRET = re.compile(
    r"(?i)(\b(?:aws_secret_access_key|secret_access_key)\s*[=:]\s*)([A-Za-z0-9/+=]{12,})"
)
_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|secret|token|api[_-]?key|access[_-]?token)\s*[=:]\s*)("
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+))"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted: bool


def redact_text(value: str) -> RedactionResult:
    """Return text with common credentials replaced, without raising on odd input."""

    text = value
    changed = False

    def replace_private(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return REDACTION

    text = _PRIVATE_KEY.sub(replace_private, text)

    def replace_url(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f"{match.group('scheme')}{REDACTION}@"

    text = _URL_CREDENTIALS.sub(replace_url, text)

    def replace_bearer(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f"{match.group(1)}{REDACTION}"

    text = _BEARER.sub(replace_bearer, text)

    for pattern in (_GITHUB_TOKEN, _OPENAI_KEY, _AWS_ACCESS_KEY):
        text, count = pattern.subn(REDACTION, text)
        changed = changed or count > 0

    def replace_assignment(match: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f"{match.group(1)}{REDACTION}"

    text = _AWS_SECRET.sub(replace_assignment, text)
    text = _ASSIGNMENT.sub(replace_assignment, text)
    return RedactionResult(text=text, redacted=changed)


def decode_and_redact(raw: bytes) -> RedactionResult:
    """Decode arbitrary command output and redact it before it is persisted."""

    return redact_text(raw.decode("utf-8", errors="replace"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))
