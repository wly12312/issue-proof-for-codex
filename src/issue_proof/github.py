"""Minimal, explicit GitHub Issue acquisition through the user's authenticated gh CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import DependencyError
from .redact import redact_text


@dataclass(frozen=True)
class IssuePayload:
    title: str
    body: str
    url: str | None


def parse_issue_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("Issue URL must use https://github.com/OWNER/REPO/issues/NUMBER")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Issue URL must not contain credentials, query parameters, or fragments")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "issues" or not parts[3].isdigit():
        raise ValueError("Issue URL must use https://github.com/OWNER/REPO/issues/NUMBER")
    owner, repo = parts[0], parts[1]
    if not owner or not repo:
        raise ValueError("Issue URL is missing an owner or repository")
    return f"https://github.com/{owner}/{repo}/issues/{int(parts[3])}"


def fetch_issue_via_gh(url: str, *, cwd: str) -> IssuePayload:
    """Fetch one issue as JSON; do not implement OAuth or fall back to arbitrary HTTP."""

    canonical = parse_issue_url(url)
    gh = shutil.which("gh")
    if not gh:
        raise DependencyError(
            "GitHub Issue fetch requires the authenticated gh CLI; install gh and run "
            "`gh auth login`, "
            "or use --issue-file instead"
        )
    try:
        completed = subprocess.run(
            [gh, "issue", "view", canonical, "--json", "title,body,url"],
            cwd=cwd,
            capture_output=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise DependencyError(
            "gh timed out while fetching the Issue; use --issue-file or retry later"
        ) from exc
    except OSError as exc:
        raise DependencyError(f"could not start gh: {exc}") from exc
    stdout = redact_text(completed.stdout.decode("utf-8", errors="replace")).text
    stderr = redact_text(completed.stderr.decode("utf-8", errors="replace")).text
    if completed.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "no diagnostic output"
        raise DependencyError(f"gh could not fetch {canonical}: {detail}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DependencyError(
            "gh returned invalid JSON; check gh version and authentication"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("title"), str):
        raise DependencyError("gh response did not contain an Issue title")
    body = data.get("body")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise DependencyError("gh response contained an invalid Issue body")
    returned_url = data.get("url") if isinstance(data.get("url"), str) else canonical
    return IssuePayload(title=data["title"], body=body, url=returned_url)
