# Security model

## Supported environment

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

## Trust boundaries

IssueProof operates on a user-selected Windows checkout. Issue bodies, comments, repository
documentation, AGENTS files, hooks, dependencies, Git remotes, command output, and Codex trace
messages are untrusted data. They do not grant permission to run commands or make external changes.

The main threats are command and shell injection, credential disclosure, invalid or oversized
input, path traversal, output symlinks or reparse points, corrupt or truncated JSONL, misleading
narrative claims, and child processes that survive a timeout.

## Input and network behavior

- Local Issue collection reads the selected Issue file and repository metadata. It makes no
  IssueProof-managed network request.
- `collect --issue-url` invokes the user's authenticated `gh issue view` command for the explicit
  GitHub Issue URL.
- Codex trace ingestion and trace-only receipt generation read only the explicit `--trace` path and
  requested repository metadata. They do not call an OpenAI API or start Codex.
- An explicit collection or verification command runs with the current Windows user's permissions.
  It may access the network, read files, modify files, or launch other programs. IssueProof does not
  sandbox that executable.
- The CLI has no path that posts comments, changes labels, closes Issues, creates pull requests,
  pushes commits, publishes releases, or changes Codex approvals and sandbox settings.

## Command execution

Only an explicitly supplied collection or verification command is treated as maintenance evidence.
Generic `--command` input is parsed to argv; Codex verification reads argv from the explicit
`--command-argv` JSON file. Execution uses `shell=False` and `stdin=DEVNULL`. Common shell
operators, substitution, redirection, and NUL bytes are rejected. Repository/runtime inspection and
doctor checks may also start detected helper programs such as Git, optional runtimes, or Codex to
read metadata or a version; use a trusted Windows environment and `PATH`.

The first argv item must be a non-empty executable. Later argv items may be empty strings so a
Windows program can receive an intentional empty argument. Windows drive paths, UNC paths, Unicode,
and spaces remain distinct argv values rather than being reconstructed through a shell.

Each command has a configurable timeout and bounded stdout/stderr capture. On timeout, IssueProof
requests `taskkill /PID <pid> /T /F`; if that fails and the parent still runs, it attempts to kill
the parent process. This is best effort: Windows permissions, protected processes, or races may
leave a descendant alive.

## Output boundaries

IssueProof resolves its output directory and generated child paths. Absolute child names, drive or
UNC child names, `..`, and paths outside the output root are rejected. Existing symlink components
are rejected. A Windows link or reparse path that resolves outside the output root fails the same
boundary comparison; permission-dependent cases must be reported as untested rather than passed.

IssueProof writes reports, receipts, Markdown, trace summaries, and a sanitized Issue snapshot only
under the selected output path. This does not restrict files changed by the separately authorized
executable.

## Redaction and bounded evidence

Before persistence, IssueProof sanitizes bounded receipt/trace projections of command arguments,
output, URLs, messages, AGENTS content, trace fields, and diagnostics. Generic collection bounds
command output and the Issue excerpt, but its sanitized Issue snapshot may contain the full supplied
Issue text. It recognizes common GitHub, OpenAI, and AWS credentials, bearer tokens,
password-like assignments, URL credentials, and private-key blocks. Pattern matching cannot
recognize every secret format.

IssueProof does not actively enumerate the full environment or create a structured environment-dump
field. An explicit command or supplied trace can still place environment content in persisted,
sanitized output projections. Generic runtime evidence records the OS, architecture, Python version,
and selected installed runtime versions. A receipt uses safe relative repository representations,
redacted remotes, bounded changed-file paths, and a digest instead of a full common Git-directory
path.

## Codex evidence handling

The parser never scans `$env:USERPROFILE\.codex`, application databases, session history,
configuration, or other private Codex state. It streams the supplied JSONL with limits for line
size, retained text, and event count.

- Invalid UTF-8, invalid JSON, non-object roots, and oversized lines are recorded with line numbers.
- Strict mode stops at the first parse error; lenient mode continues where possible.
- Unknown event types are counted and reduced to bounded type/key metadata. They are not used as
  positive evidence and require maintainer review.
- When a core baseline/verification receipt is being built, parse errors or event-limit truncation
  make only trace-specific evidence unavailable. A supplied trace cannot replace core evidence.
- Message text is omitted unless `--include-messages` is explicitly selected. Opted-in messages are
  still redacted and bounded, and the receipt records a privacy warning.
- The raw trace is not copied into the output; its SHA-256 and summary counts are recorded.

An `experimental-compatible` adapter label means nested Codex event payloads are not treated as a
permanent public contract. A final assistant message is narrative and cannot replace baseline,
command, Git, or independent verification evidence.

## Residual risk

IssueProof is an evidence tool, not a security sandbox. A malicious executable can bypass parser
checks once explicitly authorized, use the network, inspect secrets, or evade best-effort process
termination. Per-line size, retained text, and retained valid-event data are bounded, but the parser
still scans and hashes the entire selected file and currently retains one diagnostic per malformed
line; total work and diagnostics therefore grow with the input. Redaction trades forensic
completeness for lower disclosure risk and still requires human review.

Use a disposable checkout and appropriate Windows isolation for untrusted code. Preserve original
private logs outside public evidence workflows only when separately authorized and protected.
