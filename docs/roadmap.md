# Maintenance scope

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

## Current implemented scope

- Local Markdown Issue input and authenticated GitHub Issue reads through the active integration;
  the Skill main flow hands the CLI a bounded `issue.md`.
- Explicit argv execution with Windows process-tree timeout handling, bounded sanitized output,
  runtime/Git facts, stable hashes, generic JSON reports, and Markdown rendering.
- Canonical argv baseline reproduction, stable two-run baseline groups, and conservative
  same-identity verification.
- Explicit Codex JSONL ingestion with line, text, and event limits.
- Versioned, redacted `CodexMaintenanceReceipt` objects with optional trace enrichment, Git and
  AGENTS provenance, baseline/report hashes, structured checks, evidence claims, warnings, and
  deterministic Markdown.
- A Python CLI, self-contained Agent Skill directory, skills-only plugin manifest, synthetic offline
  fixtures, Draft 2020-12 schemas, and Windows CI.

## Current maintenance priorities

- Preserve Windows 10/11 behavior across Python 3.11, 3.12, and 3.14.
- Keep README, CLI, Skill, plugin metadata, schemas, fixtures, and workflows aligned with shipped
  behavior.
- Require reproducible evidence and regression tests for defect fixes.
- Keep missing, corrupt, truncated, over-limit, or conflicting evidence conservative.
- Preserve privacy redaction, output boundaries, argv separation, Unicode and space handling, UNC
  and drive paths, and timeout/process-tree behavior.

## Out of scope

The current project does not implement Linux or macOS support, a GUI, network service, telemetry,
automatic Codex-state capture, autonomous repair, a GitHub App, comment or pull-request write-back,
release publication, or general-purpose sandboxing. These are not implied by the CLI, receipt,
Skill, or plugin.

This document describes shipped scope and maintenance boundaries. It does not promise unimplemented
features or release dates.
