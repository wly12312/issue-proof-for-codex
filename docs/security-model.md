# Security model

## Scope and trust assumptions

`oss-issue-proof` is a local evidence collector for a user-selected checkout. The Issue body,
comments, README, contribution instructions, AGENTS files, repository hooks, dependencies, logs,
Git remotes, executable command, and Codex trace are not trusted equally. Issue content and Codex
messages are data, not instructions to the tool.

Threats include malicious Issue text, malicious repository instructions, shell and command
injection, secret leakage, oversized logs, invalid UTF-8, symlink escape, path traversal, remote URL
credentials, corrupt JSONL, and child processes that outlive a timeout.

## Defaults

- No network access occurs for local-file collection. GitHub URL collection only invokes the user's
  authenticated `gh issue view` command after an explicit `--issue-url`.
- The collector does not publish, push, modify an Issue, write comments, add labels, close Issues,
  create PRs, or modify repository source files.
- Only an explicitly supplied `--command` can execute. It is parsed to an argv array and executed
  with `shell=False`; common shell operators, command substitution, redirection, and NUL bytes are
  rejected.
- Subprocesses receive `stdin=DEVNULL`, a configurable timeout, and bounded stdout/stderr readers.
  Supported Windows 10/11 hosts use `taskkill /T /F` on timeout. A retained POSIX process-group
  branch is unsupported, untested, and unverified.
- Only OS, architecture, and selected runtime versions are recorded. The full environment is never
  serialized.
- Common GitHub/OpenAI/AWS credentials, bearer tokens, password-like assignments, URL credentials,
  and private-key blocks are redacted before Issue excerpts, output summaries, and diagnostics are
  written. Redaction and truncation are marked in the report.
- Every generated child path is resolved under the user-selected output directory. Absolute paths,
  `..`, and symlink components are rejected.
- The Codex adapter reads only an explicit `--trace` path. It never scans `~/.codex`, app databases,
  session history, the full environment, or configuration files. JSONL is streamed with bounded
  lines, text, and event counts; corrupt lines include their line number and strict mode stops.
- Unknown Codex events are counted and reduced to type/key metadata. Known command, tool, file-change,
  and message projections are sanitized before persistence. Full messages require explicit
  `--include-messages` and still receive size/control-character/credential handling.
- The receipt stores only a source trace SHA-256 by default. It records Git start/end state, changed
  files, safe relative AGENTS paths, hashes, sizes, scopes, and readability; it does not store full
  instructions or a common Git directory path by default.
- The receipt is a verification record, not an assertion that Codex's private event format is stable.
  Its adapter is marked `experimental-compatible`, and parse errors, unknown events, or missing
  baselines downgrade the verdict.

## Residual risk and limitations

The CLI, verification commands, process management, validators, and complete test suite are
supported only on Windows 10/11 and tested with Python 3.11, 3.12, and 3.14. Linux and macOS are
unsupported, untested, and unverified; retained cross-platform branches do not constitute a
compatibility claim.

This is not a security sandbox. An explicitly authorized executable may modify files, access the
network, inspect secrets, launch another interpreter, or evade a timeout. Parser checks reduce
accidental shell injection but cannot secure a malicious executable. Process-tree termination is
best effort and platform-dependent. Pattern redaction cannot recognize every proprietary secret
format. A malicious trace can still attempt parser resource exhaustion within configured process
limits or exploit a future parser bug. A maintainer should use a disposable checkout, review the
receipt, and apply OS-level isolation for untrusted code.

The report intentionally preserves sanitized evidence rather than raw logs. This trades forensic
completeness for a lower secret-leakage risk; keep the original process environment outside the
project if a separate, authorized incident workflow requires it.
