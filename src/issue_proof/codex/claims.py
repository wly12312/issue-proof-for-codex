"""Deterministic, evidence-only maintenance claim checks."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import DependencyError, TraceParseError

CLAIM_TYPES = {
    "bug-reproduced",
    "tests-passed",
    "lint-passed",
    "build-passed",
    "fix-verified",
    "no-source-changes",
    "files-changed",
}
CLAIM_STATUSES = {"supported", "refuted", "unverified", "not-applicable"}


@dataclass
class Claim:
    id: str
    type: str
    assertion: str | None = None
    status: str = "unverified"
    evidence_ids: list[str] = field(default_factory=list)
    reason: str = ""
    source: str = "explicit"
    heuristic: bool = False
    expected_files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "assertion": self.assertion,
            "status": self.status,
            "evidence_ids": self.evidence_ids,
            "reason": self.reason,
            "source": self.source,
            "heuristic": self.heuristic,
            "expected_files": self.expected_files,
        }


def _yaml_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value.lower() in {"true", "yes"}:
        return True
    if value.lower() in {"false", "no"}:
        return False
    if value.lower() in {"null", "none", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_yaml_scalar(item) for item in inner.split(",")]
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value.strip("\"'")


def _simple_yaml(text: str) -> Any:
    """Parse the intentionally small claims YAML shape without making PyYAML a dependency."""

    claims: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    root_claims = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "claims:":
            root_claims = True
            continue
        if stripped.startswith("- "):
            if current is not None:
                claims.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if stripped and ":" in stripped:
                key, value = stripped.split(":", 1)
                current[key.strip()] = _yaml_scalar(value)
            continue
        if current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = _yaml_scalar(value)
            continue
        if not root_claims:
            raise TraceParseError("claims YAML must contain a claims list")
    if current is not None:
        claims.append(current)
    return {"claims": claims}


def load_claim_inputs(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DependencyError(f"could not read claims file {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            data = _simple_yaml(text)
        else:
            try:
                data = yaml.safe_load(text)
            except Exception as exc:  # pragma: no cover - depends on optional parser
                raise TraceParseError(f"claims YAML is invalid: {exc.__class__.__name__}") from exc
    if isinstance(data, dict):
        data = data.get("claims")
    if not isinstance(data, list):
        raise TraceParseError("claims file must contain a list or a claims key")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise TraceParseError(f"claim {index} must be an object")
        result.append(dict(item))
    return result


def _normalise_claim(
    item: Claim | dict[str, Any], index: int, *, source: str = "explicit"
) -> Claim:
    if isinstance(item, Claim):
        return item
    claim_type = str(item.get("type", "")).strip()
    evidence_ids = item.get("evidence_ids", item.get("evidence", []))
    if isinstance(evidence_ids, str):
        evidence_ids = [evidence_ids]
    if not isinstance(evidence_ids, list) or not all(
        isinstance(value, str) for value in evidence_ids
    ):
        raise TraceParseError(f"claim {index} evidence_ids must be strings")
    expected = item.get("expected_files", item.get("files", []))
    if isinstance(expected, str):
        expected = [expected]
    if not isinstance(expected, list) or not all(isinstance(value, str) for value in expected):
        raise TraceParseError(f"claim {index} expected_files must be strings")
    return Claim(
        id=str(item.get("id", f"claim-{index:04d}")),
        type=claim_type,
        assertion=str(item["assertion"]) if item.get("assertion") is not None else None,
        evidence_ids=list(dict.fromkeys(evidence_ids)),
        source=source,
        expected_files=[value.replace("\\", "/") for value in expected],
    )


def _heuristic_claims(messages: Iterable[dict[str, Any]]) -> list[Claim]:
    patterns = (
        ("bug-reproduced", re.compile(r"\bbug\s+(?:is\s+)?reproduced\b", re.I)),
        ("tests-passed", re.compile(r"\btests?\s+(?:all\s+)?passed\b", re.I)),
        ("lint-passed", re.compile(r"\blint\s+passed\b", re.I)),
        ("build-passed", re.compile(r"\bbuild\s+passed\b", re.I)),
        ("fix-verified", re.compile(r"\bfix\s+(?:is\s+)?verified\b", re.I)),
        ("no-source-changes", re.compile(r"\bno\s+source\s+changes\b", re.I)),
    )
    result: list[Claim] = []
    seen: set[str] = set()
    for message in messages:
        text = message.get("text")
        if not isinstance(text, str):
            continue
        for claim_type, pattern in patterns:
            if claim_type not in seen and pattern.search(text):
                seen.add(claim_type)
                result.append(
                    Claim(
                        id=f"heuristic-{claim_type}",
                        type=claim_type,
                        assertion=pattern.pattern,
                        source="final-message-heuristic",
                        heuristic=True,
                    )
                )
    return result


def _command_matches(command: dict[str, Any], claim_type: str) -> bool:
    text = f"{command.get('display_command', '')} {' '.join(command.get('argv', []))}".lower()
    keywords = {
        "tests-passed": ("test", "pytest", "tox", "unittest", "check"),
        "lint-passed": ("lint", "ruff", "eslint", "flake8", "clippy"),
        "build-passed": ("build", "compile", "package", "mvn", "cargo"),
    }
    return any(keyword in text for keyword in keywords.get(claim_type, ()))


def _status_for_commands(commands: list[dict[str, Any]]) -> tuple[str, str]:
    if not commands:
        return "unverified", "No matching command evidence was supplied."
    complete = [
        item for item in commands if not item.get("timed_out") and item.get("exit_code") is not None
    ]
    if not complete:
        return "unverified", "Command evidence has no completed exit code."
    outcomes = {item.get("exit_code") == 0 for item in complete}
    if outcomes == {True}:
        return "supported", "All cited completed command evidence exited 0."
    if outcomes == {False}:
        return "refuted", "Cited command evidence contains only non-zero exits."
    return "unverified", "Cited command evidence conflicts between zero and non-zero exits."


def verify_claims(
    inputs: Iterable[Claim | dict[str, Any]],
    evidence: dict[str, Any],
    *,
    include_heuristics: bool = False,
) -> tuple[list[Claim], list[str]]:
    """Evaluate claims using only receipt evidence; absent evidence never becomes refuted."""

    claims = [_normalise_claim(item, index) for index, item in enumerate(inputs, start=1)]
    if include_heuristics:
        claims.extend(_heuristic_claims(evidence.get("final_messages", [])))
    commands = list(evidence.get("commands", []))
    command_by_id = {item.get("id"): item for item in commands if isinstance(item, dict)}
    baseline = evidence.get("baseline") if isinstance(evidence.get("baseline"), dict) else None
    verification = (
        evidence.get("verification") if isinstance(evidence.get("verification"), dict) else None
    )
    git = evidence.get("git") if isinstance(evidence.get("git"), dict) else {}
    end_git = git.get("end") if isinstance(git.get("end"), dict) else git
    trace_files = evidence.get("trace_files", [])
    all_ids = set(evidence.get("evidence_ids", []))
    all_ids.update(command_by_id)
    all_ids.update({"baseline-reproduction", "verification", "git-end", "trace-files"})
    warnings: list[str] = []
    for claim in claims:
        if claim.type not in CLAIM_TYPES:
            claim.status = "not-applicable"
            claim.reason = f"Unsupported claim type: {claim.type or '<empty>'}."
            continue
        if not claim.evidence_ids:
            if claim.type in {"tests-passed", "lint-passed", "build-passed"}:
                claim.evidence_ids = [
                    item["id"] for item in commands if _command_matches(item, claim.type)
                ]
            elif claim.type == "bug-reproduced" and baseline is not None:
                claim.evidence_ids = ["baseline-reproduction"]
            elif claim.type == "fix-verified" and verification is not None:
                claim.evidence_ids = ["verification"]
            elif claim.type == "no-source-changes" and git:
                claim.evidence_ids = ["git-end"]
            elif claim.type == "files-changed" and (git or trace_files):
                claim.evidence_ids = ["git-end", "trace-files"]
        missing = [item for item in claim.evidence_ids if item not in all_ids]
        if missing:
            claim.status = "unverified"
            claim.reason = f"Cited evidence ID(s) are unavailable: {', '.join(missing)}."
            continue
        if claim.type in {"tests-passed", "lint-passed", "build-passed"}:
            cited = [command_by_id[item] for item in claim.evidence_ids if item in command_by_id]
            claim.status, claim.reason = _status_for_commands(cited)
        elif claim.type == "bug-reproduced":
            outcome = baseline.get("outcome") if baseline else None
            if outcome == "reproduced":
                claim.status, claim.reason = (
                    "supported",
                    "Baseline reproduction evidence is reproduced.",
                )
            elif outcome in {"not-reproduced", "refuted"}:
                claim.status, claim.reason = (
                    "refuted",
                    "Baseline evidence did not reproduce the reported bug.",
                )
            else:
                claim.status, claim.reason = (
                    "unverified",
                    "Baseline reproduction evidence is incomplete.",
                )
        elif claim.type == "fix-verified":
            outcome = verification.get("outcome") if verification else None
            if not baseline:
                claim.status, claim.reason = (
                    "unverified",
                    "No baseline was supplied for fix verification.",
                )
            elif outcome == "verified":
                claim.status, claim.reason = (
                    "supported",
                    "Independent verification passed against a reproduced baseline.",
                )
            elif outcome in {"not-fixed", "refuted"}:
                claim.status, claim.reason = (
                    "refuted",
                    "The independent verification evidence still fails.",
                )
            else:
                claim.status, claim.reason = "unverified", "Independent verification is incomplete."
        elif claim.type == "no-source-changes":
            changed = end_git.get("changed_files", []) if isinstance(end_git, dict) else []
            if isinstance(changed, list) and not changed:
                claim.status, claim.reason = (
                    "supported",
                    "Git end-state evidence lists no changed files.",
                )
            elif isinstance(changed, list):
                claim.status, claim.reason = (
                    "refuted",
                    "Git end-state evidence lists changed files.",
                )
            else:
                claim.status, claim.reason = (
                    "unverified",
                    "Git changed-file evidence is unavailable.",
                )
        elif claim.type == "files-changed":
            actual: set[str] = set()
            if isinstance(end_git, dict) and isinstance(end_git.get("changed_files"), list):
                actual.update(str(item).replace("\\", "/") for item in end_git["changed_files"])
            if isinstance(trace_files, list):
                actual.update(
                    str(item.get("path", "")).replace("\\", "/")
                    for item in trace_files
                    if isinstance(item, dict) and item.get("path")
                )
            expected = set(claim.expected_files)
            if not expected:
                claim.status, claim.reason = (
                    "unverified",
                    "files-changed claims require expected_files.",
                )
            elif actual == expected:
                claim.status, claim.reason = (
                    "supported",
                    "Git/trace file evidence matches expected_files.",
                )
            elif actual and expected.isdisjoint(actual):
                claim.status, claim.reason = (
                    "refuted",
                    "Observed changed files do not match expected_files.",
                )
            else:
                claim.status, claim.reason = (
                    "unverified",
                    "Observed and expected changed-file sets conflict.",
                )
        if claim.heuristic:
            claim.reason = "Heuristic final-message candidate; " + claim.reason
            warnings.append(f"claim {claim.id} came from heuristic final-message extraction")
    return claims, warnings
