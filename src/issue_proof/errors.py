"""Typed errors and stable CLI exit-code mapping."""

from __future__ import annotations


class IssueProofError(Exception):
    """Base error with a stable tool-level exit code."""

    exit_code = 6

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class CliUsageError(IssueProofError):
    exit_code = 2


class DependencyError(IssueProofError):
    exit_code = 4


class OutputPathError(IssueProofError):
    exit_code = 4


class CommandParseError(IssueProofError):
    exit_code = 2


class ExecutionTimeoutError(IssueProofError):
    exit_code = 5


class SchemaValidationError(IssueProofError):
    exit_code = 3


class TraceParseError(IssueProofError):
    exit_code = 3


class InternalError(IssueProofError):
    exit_code = 6
