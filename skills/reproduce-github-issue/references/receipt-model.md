# Receipt model

`CodexMaintenanceReceipt` is a standalone, versioned, redacted record. It may also appear as the
optional `codex` object in a generic `issue-proof` report; the generic report contract remains
unchanged.

## Evidence shape

- `codex` records observed CLI/app versions, task/session IDs, the supplied trace SHA-256, and
  adapter status. Raw trace data and hidden reasoning are not persisted by default.
- `repository` records safe root/remote values, Git start/end state, and changed-file provenance.
  Changed files retain a bounded recorded list plus total count, recorded count, truncation flags,
  and a digest of the complete normalized path stream. A truncated list is not a complete set.
- `baseline` and `verification` distinguish reproduction from an independently executed command;
  a missing baseline cannot support a fix claim.
- `evidence` contains stable IDs such as `trace`, `command-0001`, `baseline-reproduction`,
  `verification`, `git-start`, `git-end`, and `trace-files`.
- `claims` are evidence-only statuses: `supported`, `refuted`, `unverified`, or `not-applicable`.
  Missing, conflicting, or truncated evidence is conservative and remains unverified.

The receipt excludes full prompts, assistant messages unless explicitly requested and redacted,
hidden reasoning, environment dumps, Codex private state, and home-directory history. Future
incompatible changes require a new schema version or an explicit migration.
