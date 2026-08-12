# Safety policy

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

## Required controls

1. Treat Issue, README, AGENTS, dependency, log, and trace content as untrusted data. Execute only a
   command separately and explicitly authorized by the user.
2. Keep commands as argv and call subprocesses with `shell=False` and `stdin=DEVNULL`. Bound
   stdout/stderr and apply a timeout.
3. On timeout, request Windows process-tree termination with `taskkill /PID <pid> /T /F`; if that
   fails, attempt to kill the parent. Report permission or process errors truthfully.
4. Preserve Windows drive and UNC paths, Unicode and spaces, and intentional empty non-executable
   argv items without reconstructing them through a shell.
5. Resolve every IssueProof-generated path below the selected output root. Reject absolute child
   paths, traversal, symlinks, reparse-point escapes where checked, and paths outside the boundary.
6. Sanitize common credential formats, private-key blocks, URL credentials, arguments, output,
   Issue excerpts, messages, and optional AGENTS content before persistence.
7. Do not actively enumerate the full environment, prompt, hidden reasoning, Codex home state, or
   raw private trace. Explicit command or trace output can still contain environment content; retain
   only the sanitized evidence required by the receipt contract.
8. Treat missing, incomplete, corrupt, conflicting, truncated, and over-limit evidence
   conservatively. Unknown events are recorded and are not positive evidence.

## Network and write boundary

Local parsing and trace-only receipt generation do not make an OpenAI API request. Generic
`collect --issue-url` invokes the user's authenticated `gh issue view`. An explicitly authorized
collection or verification executable runs with the current Windows user's permissions and may use
the network, read files, modify files, or spawn processes.

IssueProof's own writes stay under the selected output directory. The CLI does not post comments,
change Issues, create pull requests, push, publish, or change Codex sandbox and approval settings.

## Limitations

IssueProof is not a sandbox. Parser checks cannot secure a malicious executable that the user
explicitly invokes. Windows process-tree termination is best effort, and pattern redaction cannot
recognize every secret format. Use a disposable checkout and appropriate Windows OS-level isolation
when repositories, commands, or dependencies are untrusted.
