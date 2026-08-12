# Evidence model

`report.json` is the machine-readable contract. `report.md` is a deterministic rendering of the
same data. Both are produced locally and should be attached or reviewed as a pair.

## Required sections

- `schema_version`, `tool_version`, `run_id`, and timezone-aware `created_at` identify the contract
  and run.
- `issue` records `local-file` or `github-url`, a redacted location, title, a SHA-256 hash of the
  sanitized normalized body, and a bounded sanitized excerpt. It does not preserve the raw Issue.
- `repository` records the resolved root, redacted origin URL, HEAD SHA, branch, and dirty state.
- `runtime` records OS, architecture, and selected versions for Python, Node, Rust, or Java when
  the executable is present. It does not dump environment variables.
- `execution` records sanitized argv and display command, cwd, ISO timestamps, duration, exit
  code, timeout state, and bounded stdout/stderr summaries with SHA-256, byte count, truncation,
  and redaction flags.
- `artifacts` contains relative output paths and SHA-256 hashes. The collector currently includes a
  sanitized `issue-source.md` snapshot; it does not scan the repository or copy source files.
- `reproduction.outcome` is `reproduced`, `not-reproduced`, `inconclusive`, or `not-run`.
- `verification.outcome` is `verified`, `not-fixed`, `inconclusive`, or `not-applicable`.
- `warnings`, `security_events`, and `notes` preserve limitations and human context.

## Outcome semantics

Collection classifies one explicitly supplied completed command: non-zero is `reproduced`, zero is
`not-reproduced`, timeout is `inconclusive`, and no command is `not-run`. This is a single-run
observation, not a claim that the failure is deterministic.

Verification is conservative. It requires a baseline with `reproduced`, a completed baseline with
an exit code, matching sanitized argv, and a completed current command. A current zero exit is
`verified`; a current non-zero exit is `not-fixed`; all other comparisons are `inconclusive`.
Verification reports the baseline run ID and stability note so maintainers can request repeated
runs when flakiness matters.

## Hashing and rendering

All hashes are lowercase SHA-256. Field order and Markdown section order are stable. Timestamps are
ISO 8601 with UTC `Z`. Output is sanitized before hashing and persistence, so a hash identifies the
stored sanitized summary, not an unrecoverable secret-bearing stream.
