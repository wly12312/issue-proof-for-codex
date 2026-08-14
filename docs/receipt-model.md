# CodexMaintenanceReceipt model

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

`CodexMaintenanceReceipt` is a standalone, versioned, redacted record. The generic report keeps
`schema_version: 1.0.0` and may carry an optional `codex` object; a standalone receipt uses
`receipt_schema_version: 2.0.0` and a Draft 2020-12 repository schema. The core receipt does not
require a Codex trace.

## Top-level sections

| Section | Evidence | Important boundary |
| --- | --- | --- |
| `receipt_schema_version`, `receipt_type`, `tool_version`, `identity_mode` | Contract, producer, and repository identity policy | Not a package or release attestation |
| `codex` | Observed CLI/app versions, task/session IDs, trace digest, adapter status | Raw trace is not persisted |
| `repository` | Safe root, redacted remote, adjacent receipt-time Git snapshots, changed-file counts/list/digest | These snapshots are not the maintenance command's before/after state; a truncated list is incomplete |
| `issue` | Supplied URL/number or local Issue metadata | Full Issue body is not stored in the receipt |
| `baseline` | Reproduction outcome, report ID, command evidence, stability | Missing or invalid baseline cannot support a fix claim |
| `baseline_group` | Run IDs, report hashes, stability rule, and identity comparisons | One run is `single-run`, not stable reproduction |
| `commands` | Sanitized argv, display, cwd, exit, timeout, bounded streams | Explicit commands are not sandboxed |
| `verification` | Outcome, actual baseline report SHA-256, and recomputed argv/cwd/repository/remote/HEAD/timeout/termination/runtime/tool fields | Mismatch, missing hash, or incomplete identity is inconclusive |
| `checks` | Structured additional regression-check reports with `passed`, `failed`, or `inconclusive` status | A collection report's `not-reproduced` is mapped to `passed` only after its command exits zero |
| `report_hashes` | SHA-256 hashes for baseline, verification, and check reports | Hashes identify inputs; they do not prove causality |
| `agents` | Relative paths, hashes, sizes, scopes, readability, warnings | Content requires explicit opt-in |
| `trace`, `trace_status` | Optional trace filename/digest, status, counts, limit and message mode | Missing, invalid, or truncated trace affects trace evidence only |
| `evidence` | Stable IDs and bounded summaries | Claims may cite only available IDs |
| `claims` | Supported, refuted, unverified, or not-applicable conclusions | Narrative alone cannot support a claim |
| `warnings`, `redactions`, `unknown_events`, `parse_errors` | Uncertainty and privacy context | Trace parse issues do not replace core verification evidence |
| `verdict` | Conservative receipt summary | Not proof of causality or overall code safety |

IssueProof does not actively import a full prompt, hidden reasoning, structured environment dump,
Codex configuration, home history, or private application databases. Explicit command or trace
output can still contain environment content. Assistant messages are omitted unless explicitly
requested and are always treated as narrative.

## Evidence IDs and claims

Stable receipt-generated IDs include `trace`, `event-000001`, command IDs,
`baseline-reproduction`, `verification`, `verification-command`, `git-start`, `git-end`,
`trace-files`, and `agents-0001`.

Supported explicit claim types are:

- `bug-reproduced`
- `tests-passed`
- `lint-passed`
- `build-passed`
- `fix-verified`
- `no-source-changes`
- `files-changed`

Tests, lint, and build claims require completed cited command evidence with exit code zero. A cited
command set containing incomplete evidence remains unverified. `fix-verified` requires a stable
baseline group, matching execution identity including `same_head`, the verification report's
baseline SHA-256 matching the supplied baseline, non-timeout execution, and verification exit code
zero. Missing, conflicting, corrupt, or incomplete core evidence yields `unverified` or
`inconclusive`, not success.

Changed-file provenance retains a bounded normalized list, total and recorded counts, overflow and
truncation flags, and a digest of the complete normalized path stream when available. Claims that
require a complete changed-file set remain unverified if the set is incomplete.

The two Git snapshots are captured back-to-back while constructing the receipt. They describe the
checkout at capture time; they do not establish which files a prior Codex or verification command
changed. Record true task-start provenance separately when attribution matters.

## Validation and compatibility

Receipt generation runs the package's receipt validator before writing output. The repository's
`schemas\codex-maintenance-receipt.schema.json` describes the standalone JSON contract for external
Draft 2020-12 validation. The `issue-proof validate` CLI command auto-detects and validates either a
generic `report.json` or a standalone receipt.

Old generic reports without a `codex` key continue to load under schema `1.0.0`. Legacy standalone
receipts with schema `1.0.0` remain loadable; a future incompatible receipt shape requires an
explicit migration or a new receipt schema version and must not be silently interpreted as the
existing contract.
