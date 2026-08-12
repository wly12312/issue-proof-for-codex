# CodexMaintenanceReceipt model

`CodexMaintenanceReceipt` is a standalone versioned object. It can also be embedded as the optional
`codex` object in the existing `issue-proof` report; the generic report's required fields and
`schema_version: 1.0.0` remain unchanged.

## Top-level sections

| Section | Evidence carried | Privacy rule |
| --- | --- | --- |
| `receipt_schema_version`, `receipt_type`, `tool_version` | Contract and producer identity | No hidden runtime state |
| `codex` | observed CLI/app version, task/session IDs, source trace SHA-256, adapter status | IDs are null when absent; raw trace is false by default |
| `repository` | safe root representation, redacted remote, HEAD/branch/dirty, worktree and common-dir digest, start/end state, bounded changed files, total/recorded counts, truncation flags, and a complete-set digest | no full home path or common Git directory; a truncated path list is never treated as complete |
| `issue` | URL/number/local location and body hash when provided | no full Issue body by default |
| `baseline` | reproduction outcome, report ID, command evidence, stability | absent baseline cannot support a fix claim |
| `commands` | safe argv/display/cwd, exit, duration, timeout, bounded stream summaries | output is redacted and size bounded |
| `verification` | independent outcome and relation to baseline/argv | uses explicit command evidence only |
| `agents` | relative path/hash/size/scope/readability and warnings | full content only with explicit opt-in and redaction |
| `trace` | filename, digest, line/event counts, unknown count, message mode | no raw JSONL |
| `evidence` | stable IDs and short conclusions | every claim points to these IDs |
| `claims` | supported/refuted/unverified/not-applicable status and reason | missing evidence is unverified, not refuted |
| `warnings`, `redactions`, `unknown_events`, `parse_errors` | downgrade context | never silently discard uncertainty |
| `verdict` | verified/partially-verified/unverified/refuted/inconclusive | conservative summary, not a causal proof |

The object intentionally contains no full prompt, assistant transcript, hidden reasoning, environment
dump, model token usage, Codex config, home history, or private app database content.

Changed-file provenance uses a conservative entry and per-path byte limit. The receipt retains the
complete normalized path-stream SHA-256, total count, recorded count, and overflow/truncation flags;
warnings describe the omission without including omitted paths. Claims that require a complete
changed-file set remain `unverified` when truncation occurs.

## Evidence IDs and claims

Stable IDs include `trace`, `event-000001`, `command-0001`, `baseline-reproduction`,
`verification`, `git-start`, `git-end`, `trace-files`, and `agents-0001`. An explicit claims JSON or
small YAML file names the claim type and optional evidence IDs. Supported types are:

- `bug-reproduced`
- `tests-passed`
- `lint-passed`
- `build-passed`
- `fix-verified`
- `no-source-changes`
- `files-changed`

Tests/lint/build are supported only by completed cited commands with exit code zero. `fix-verified`
requires baseline `reproduced`, the same argv, non-timeout execution, and verification exit zero.
`files-changed` compares expected files with Git/trace evidence. A missing, corrupt, or conflicting
piece of evidence yields `unverified`; it is never converted into a negative finding. Optional final
message extraction is heuristic, labeled, and never an LLM or paid API call.

## Migration and compatibility

Old reports load without a `codex` key. New generic reports may add that optional object without
changing the required report schema. Standalone receipts have their own schema file and version.
Future incompatible receipt changes must add a migration or a new schema version; the loader rejects
unknown versions instead of silently interpreting them.
