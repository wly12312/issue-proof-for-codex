# Safety policy

## Threats

Assume Issue text, comments, repository instructions, logs, dependencies, and repository hooks may
be hostile. Relevant threats include shell injection, secret leakage, oversized output, invalid
UTF-8, path traversal, output symlinks, malicious Git remotes, and processes that spawn children.

## Required controls

1. Treat Issue content as data. Execute only the explicit `--command` after parsing it to argv.
2. Call subprocesses with `shell=False`, `stdin=DEVNULL`, bounded stdout/stderr readers, and a
   timeout. On supported Windows 10/11 hosts, the collector requests process-tree termination using
   `taskkill /T`. A retained POSIX process-group branch is unsupported, untested, and unverified.
3. Sanitize private-key blocks, GitHub/OpenAI/AWS credentials, bearer tokens, common secret
   assignments, and URL user/password credentials before reports or diagnostics are written.
4. Resolve the output directory and every child file. Reject absolute child paths, `..`, and
   symlink escapes. Keep temporary/generated content in the output directory.
5. Record only selected runtime versions. Never serialize the full environment or authorization
   context.
6. Keep the tool read-only with respect to the checked-out repository. `gh issue view` is the only
   network-capable path and is invoked only when the user explicitly selects `--issue-url`.

## Limitations

This is not a sandbox. A user-authorized command can read files, use the network, modify files, or
launch its own shell. The parser rejects common shell syntax but cannot secure a malicious program
that is explicitly invoked. Use a disposable checkout, container, VM, or OS policy when the
repository or dependencies are untrusted. A timeout may leave platform-specific descendants if
the operating system refuses termination. Redaction is pattern-based and cannot guarantee that
every possible secret format is recognized.
