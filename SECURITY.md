# Security policy

## Supported environment

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

Security reports should describe behavior in a supported environment. Reports that depend only on
an unsupported platform cannot be represented as verified project defects.

## Report a vulnerability

Do not disclose a suspected vulnerability in a public Issue. If the repository Security tab offers
private vulnerability reporting, use it. Otherwise contact a maintainer privately before sharing
details. The project does not claim that a separately monitored security inbox or a guaranteed
response timeline exists.

Include only the information needed to reproduce and assess the problem:

- the affected `issue-proof` version;
- Windows 10 or Windows 11 and the Python version;
- sanitized output from `issue-proof doctor`, when relevant;
- minimal PowerShell reproduction steps;
- whether the issue affects command execution, redaction, output boundaries, trace parsing,
  evidence claims, receipt validation, Skill delegation, or process-tree termination;
- the actual Windows error for any permission-dependent symlink, reparse-point, or `taskkill` case.

Do not attach credentials, private keys, raw private Issue bodies, private repository URLs, raw
Codex traces, full prompts, environment dumps, or unredacted logs. Create a small synthetic fixture
when possible.

## Security boundary

IssueProof is not a sandbox. Its own local parsing does not make an OpenAI API request, and its own
generated files are constrained to the selected output directory. Generic `collect --issue-url`
invokes the user's authenticated `gh issue view` command. An explicitly authorized collection or
verification command runs with the current Windows user's permissions and may access the network,
read secrets, modify files, or spawn processes.

Commands are executed as argv with `shell=False`; common shell operators, substitution,
redirection, and NUL bytes are rejected. Command output and receipt/trace projections are bounded
and sanitized before persistence. Generic collection sanitizes its Issue snapshot but can retain
the full supplied Issue text. Redaction is pattern-based and cannot recognize every possible
proprietary secret format.

Windows timeouts request `taskkill /T /F` and fall back to terminating the parent process when
needed. Process-tree termination is best effort and can be limited by Windows permissions or
process state. Use a disposable checkout and suitable Windows OS-level isolation for untrusted
commands or dependencies.

See [`docs/security-model.md`](docs/security-model.md) for the detailed threat model and residual
risks.
