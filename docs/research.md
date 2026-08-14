# Architecture decisions

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

This document records durable implementation boundaries. It intentionally omits machine-specific
tool versions, transient registry searches, local dependency failures, adoption claims, and future
feature promises.

## Evidence before conclusions

IssueProof separates four kinds of information:

1. generic baseline reports from an explicitly supplied canonical argv;
2. an independently executed verification command using the same argv and machine identity;
3. optional bounded projections from an explicitly supplied Codex JSONL trace;
4. claims that cite stable receipt evidence IDs.

A single failing baseline is an observation, not proof that a bug is deterministic. An assistant
message is narrative, not verification. A fix conclusion requires a stable two-run baseline group,
matching argv/cwd/repository/remote/HEAD/timeout/termination/runtime/tool identities, and a
completed non-timeout zero exit from independent verification.

## Codex adapter boundary

The adapter accepts a JSONL stream with documented outer event-family names and locally tested item
projections. Nested payloads are version-sensitive, so the adapter is labeled
`experimental-compatible`. Unknown event types are counted and excluded from positive evidence.
Parse errors and event-limit truncation make trace-specific evidence unavailable; they do not by
themselves make a separately supported core receipt inconclusive.

The adapter reads only the explicit trace path. It does not start Codex, call an OpenAI API, scan
Codex home/history/configuration, or import hidden reasoning. Raw JSONL is represented by a digest
and bounded summary rather than being copied into the receipt directory.

## Command and Windows process boundary

Commands are supplied separately from Issue, README, AGENTS, and trace text. Generic command input
is parsed into argv; Codex verification receives a JSON string array. The implementation uses
`shell=False`, keeps Windows path and argument boundaries, bounds output, and applies a timeout.

On timeout, supported Windows hosts request `taskkill /T /F` and fall back to killing the parent
process if needed. This is best effort and not a sandbox. An explicitly authorized executable can
access the network, inspect secrets, modify files, or launch other programs.

## Data and privacy boundary

The runtime package uses the Python standard library. Reports retain selected runtime and Git facts,
sanitized Issue and command evidence, stable SHA-256 digests, and explicit uncertainty. IssueProof
does not actively enumerate the full environment or create a structured environment-dump field;
explicit command or trace output can still contain environment content.

Generated IssueProof files stay below the selected output directory. Absolute child paths, traversal,
and symlink escape are rejected. This output restriction does not constrain the separately
authorized command.

## Skill and plugin boundary

The Agent Skill is a self-contained directory with `SKILL.md`, four reference documents, agent UI
metadata, and a delegate script. Independent installation requires copying the complete directory
and separately installing the `issue-proof` CLI. The delegate does not load repository source by
path.

The Codex plugin is skills-only. It declares the Skill directory and no app, MCP server, or connected
service. The Python wheel installs only the runtime package and CLI; it does not register the Skill
or plugin.

## Schema boundary

Generic reports retain schema version `1.0.0`. Standalone receipts use versioned contract `2.0.0`.
The CLI `validate` command auto-detects generic reports and standalone receipts. Receipt generation
performs internal validation, and the repository supplies a Draft 2020-12 standalone receipt schema
for external consumers.
