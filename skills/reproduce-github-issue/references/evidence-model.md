# Evidence model

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

`report.json` is the machine-readable generic report. `report.md` is a deterministic rendering of
the same report fields. Both are generated locally under an explicit output directory.

## Generic report sections

- `schema_version`, `tool_version`, `run_id`, and `created_at` identify the contract and run.
- `issue` records the selected local file or GitHub URL, sanitized location/title/excerpt, and a
  digest of the sanitized normalized body. It does not preserve the raw Issue.
- `repository` records the resolved root, redacted origin, HEAD, branch, dirty state, and a
  repository identity digest.
- `runtime` records Windows, architecture, Python, and selected installed runtime versions without
  dumping environment variables.
- `execution` records sanitized argv/display/cwd, times, duration, exit code, timeout state,
  termination/capture policy, and argv/cwd/policy identities plus bounded stdout/stderr summaries
  and digests.
- `artifacts` records relative IssueProof-generated paths and SHA-256 values. The collector may
  include a sanitized `issue-source.md`; it does not scan or copy repository source.
- `reproduction`, `verification`, `warnings`, `security_events`, and `notes` preserve the observed
  outcome and limitations.

## Outcome semantics

For a completed baseline command, non-zero is `reproduced` and zero is `not-reproduced`. A timeout
is `inconclusive`; no command is `not-run`. This is a single-run observation, not proof of stability
or causality. The top-level receipt requires at least two matching completed non-zero, non-timeout
baseline reports before it calls the group stable.

Verification is conservative. It records matching argv, cwd, repository, remote, HEAD, timeout,
termination, runtime, and tool identities, plus the SHA-256 of the baseline report actually used.
It requires baseline `reproduced`, a completed non-zero baseline, and a completed current command. A
current zero exit is `verified`; a current non-zero exit is `not-fixed`; missing, mismatched, or
timeout evidence is `inconclusive`. A receipt recomputes these comparisons from report fields.

Additional regression checks have their own three-state semantics: `passed`, `failed`, or
`inconclusive`. A generic collection report may say `verification.outcome: not-applicable` and
`reproduction.outcome: not-reproduced`; the receipt maps that source evidence to `passed` only when
the command completed with exit code zero.

The first argv item must identify a non-empty executable. Later items may be empty strings when the
Windows target program requires an explicit empty argument.

## Privacy and hashes

SHA-256 values are lowercase. Output is sanitized before persistence and hashing, so a stream digest
identifies the stored sanitized summary rather than an original secret-bearing stream. Pattern
redaction and bounded summaries reduce disclosure risk but do not replace review.
