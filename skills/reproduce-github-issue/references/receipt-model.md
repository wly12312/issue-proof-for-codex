# Receipt model

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

`CodexMaintenanceReceipt` is a standalone, versioned, redacted record. A generic report may also
carry an optional `codex` object while retaining generic schema version `1.0.0`.

## Evidence shape

- `codex` records observed CLI/app versions, task/session IDs, source trace SHA-256, adapter status,
  and whether bounded message content was requested. Raw trace data is not persisted.
- `repository` records safe root/remote values, adjacent Git snapshots taken during receipt
  construction, and bounded changed-file provenance. These are not the maintenance command's
  before/after state, and a truncated path list is never treated as complete.
- `baseline` and `verification` distinguish reproduction evidence from independently executed
  same-argv evidence. A missing or invalid baseline cannot support a fix claim.
- `commands` contains bounded, sanitized command evidence. An incomplete cited command set remains
  unverified even if another cited command exited zero.
- `evidence` contains stable IDs such as `trace`, command and event IDs, `baseline-reproduction`,
  `verification`, `verification-command`, `git-start`, `git-end`, and `trace-files`.
- `claims` use `supported`, `refuted`, `unverified`, or `not-applicable`. They may cite only evidence
  IDs that exist in the receipt.
- `warnings`, `redactions`, `unknown_events`, and `parse_errors` make uncertainty visible. Unknown
  events are not positive evidence; missing, corrupt, truncated, or over-limit trace evidence cannot
  produce a verified verdict.

IssueProof does not actively import a full prompt, hidden reasoning, structured environment dump,
Codex configuration, home history, or private application databases. Explicit command or trace
output can still contain environment content. Assistant messages are omitted unless explicitly
requested and cannot replace independent evidence.

## Completion rule

A verified fix requires a reproduced baseline, matching argv, a completed non-timeout verification
with exit code zero, and complete required evidence. If any prerequisite is absent or inconsistent,
state the actual unverified, refuted, or inconclusive result.

Receipt generation performs internal validation. The CLI `issue-proof validate` command validates a
generic `report.json`, not a standalone receipt; external consumers may use the repository's Draft
2020-12 receipt schema.
