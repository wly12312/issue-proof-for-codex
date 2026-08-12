# IssueProof for Codex

`oss-issue-proof` records privacy-filtered evidence for an explicitly selected open-source
maintenance task. It can reproduce a failure, import an explicitly supplied Codex JSONL trace, run
a matching verification command, and produce a redacted `CodexMaintenanceReceipt` for maintainer
review.

This is an independent community project. It is not an OpenAI product, does not claim OpenAI
endorsement, and does not replace human review.

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

The supported CLI, process management, validators, Skill workflow, and CI use Windows behavior.
Code that happens to import or run elsewhere does not establish support.

## What it records

The generic report records a local Issue or authenticated GitHub Issue, an optional explicit
command, bounded stdout and stderr, selected runtime and Git facts, reproduction status, and a
deterministic Markdown rendering.

The Codex receipt can additionally record:

- the SHA-256 of an explicitly supplied JSONL trace, without copying the raw trace;
- bounded projections of known command, file-change, tool, and message events;
- baseline and independently executed verification evidence;
- repository-scoped AGENTS provenance and adjacent Git snapshots taken during receipt construction;
- evidence-backed claims and a conservative verdict;
- warnings, redactions, unknown event types, and parse errors.

A receipt does not prove causality. A `verified` result requires a reproduced baseline, the same
argv, a completed non-timeout verification with exit code zero, and no receipt condition that makes
the result inconclusive. A final assistant message is narrative, not independent verification.

## Install the CLI

Use one of the tested Python versions. From a source checkout in PowerShell:

```powershell
py -3.12 -m venv .venv
$Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $Python -m pip install .
& $Python -m issue_proof --version
& $Python -m issue_proof doctor
```

After downloading the `0.1.3` wheel from the matching GitHub Release, install it into a clean
environment with:

```powershell
py -3.12 -m venv .venv
$Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $Python -m pip install '.\oss_issue_proof-0.1.3-py3-none-any.whl'
& $Python -m issue_proof doctor
```

Python package dependencies are standard-library only. A trusted Git executable is required for
generic collect/verify repository inspection. The authenticated `gh` CLI is optional and is needed
only for generic collection with `--issue-url`. Codex is optional. The
`issue-proof codex doctor` command detects a local `codex.cmd` or `codex` executable and runs only
its version command.

## Reproduce and verify a local example

The following PowerShell walkthrough starts with a failing deterministic command, creates the
fixture's simulated fix marker, and verifies the same command. Run it from a clean source checkout:

```powershell
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
$Marker = '.\.issue-proof\manual-run\fixed.marker'
if (Test-Path -LiteralPath $Marker) {
    throw "The example marker already exists: $Marker"
}

& $Cli collect `
    --issue-file '.\examples\issue.md' `
    --command '.\.venv\Scripts\python.exe .\examples\deterministic_bug.py' `
    --output '.\.issue-proof\manual-run\baseline'

New-Item -ItemType File -Path $Marker -Force | Out-Null

& $Cli verify `
    --baseline '.\.issue-proof\manual-run\baseline\report.json' `
    --command '.\.venv\Scripts\python.exe .\examples\deterministic_bug.py' `
    --output '.\.issue-proof\manual-run\verified'

& $Cli validate '.\.issue-proof\manual-run\verified\report.json'
& $Cli render `
    '.\.issue-proof\manual-run\verified\report.json' `
    --output '.\.issue-proof\manual-run\verified\report-rendered.md'
```

`collect` classifies a completed non-zero command as `reproduced`. `verify` requires the baseline
argv to match the verification argv; a different command is inconclusive.

## Use an explicit Codex trace

Trace ingestion and trace-only receipt generation are offline: they do not call an OpenAI API,
start a Codex task, or scan Codex private state. They read only paths explicitly supplied by the
user plus requested repository metadata. `codex verify` additionally executes the explicit argv in
`--command-argv`; that executable may access the network, modify files, or spawn processes with the
current Windows user's permissions.

```powershell
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
& $Cli codex doctor
& $Cli codex ingest `
    --trace '.\codex-run.jsonl' `
    --output '.\.issue-proof\codex-run'
& $Cli codex receipt `
    --trace '.\codex-run.jsonl' `
    --issue-file '.\issue.md' `
    --output '.\.issue-proof\receipt'
& $Cli codex verify `
    --baseline '.\.issue-proof\baseline\report.json' `
    --trace '.\codex-run.jsonl' `
    --command-argv '.\verify-command.json' `
    --repo-root '.' `
    --output '.\.issue-proof\verified'
```

`verify-command.json` contains a JSON argv array, not a shell command. The first item must be a
non-empty executable; later items may be empty strings when the target command requires an explicit
empty argument.

```json
{
  "argv": ["pytest", "tests\\test_bug.py", "-q"]
}
```

The complete deterministic offline Codex fixture walkthrough is in
[`examples/codex-maintenance/`](examples/codex-maintenance/). Its traces are synthetic fixtures, not
records of a real Codex task.

## Network, command, and write boundaries

- Local Issue parsing and trace parsing do not make network requests.
- Generic `collect --issue-url` invokes the user's authenticated `gh issue view` command.
- IssueProof never posts comments, labels or closes Issues, creates pull requests, pushes, publishes,
  or changes Codex sandbox and approval settings.
- IssueProof's own generated files stay under the selected output directory. An explicitly
  authorized command is not sandboxed by IssueProof and may modify the checkout or other resources.
- Commands execute as argv with `shell=False`; generic `--command` rejects unquoted shell operators,
  redirection, substitution, and NUL. JSON `--command-argv` treats operator characters literally
  and rejects NUL.
- Windows timeouts request `taskkill /T /F`; if that fails, IssueProof attempts to terminate the
  parent process. Process-tree termination remains best effort.

Use a disposable checkout and appropriate Windows OS-level isolation for untrusted repositories or
commands.

## Privacy defaults

- The trace parser never scans `$env:USERPROFILE\.codex`, application databases, session history,
  the full environment, or Codex configuration.
- JSONL has per-line, retained-text, and retained valid-event limits. The selected file is still
  scanned and hashed in full, and lenient mode retains one diagnostic per corrupt line; strict mode
  stops at the first parse error.
- Unknown event types are counted and reduced to bounded metadata. They are not positive evidence;
  inspect them before relying on a receipt.
- Parse errors and event-limit truncation make a receipt inconclusive.
- Command output and receipt/trace projections of arguments, paths, URLs, messages, and optional
  AGENTS content are sanitized and bounded before persistence. Generic collection sanitizes the
  supplied Issue snapshot but can retain its full text; review the selected file and output size.
- `--include-messages` adds a privacy warning to the generated receipt and still stores only
  sanitized, bounded text. Hidden reasoning and raw conversation history are not imported.
- Remote credentials are redacted, and the common Git directory is represented by a digest.

See [`docs/security-model.md`](docs/security-model.md) and [`SECURITY.md`](SECURITY.md).

## Schemas and validation

`issue-proof validate` validates the generic `report.json` contract, whose schema version remains
`1.0.0`. The repository and source distribution also contain Draft 2020-12 JSON Schemas for the
generic report and standalone receipt:

- [`schemas/issue-proof.schema.json`](schemas/issue-proof.schema.json)
- [`schemas/codex-maintenance-receipt.schema.json`](schemas/codex-maintenance-receipt.schema.json)

The CLI has no standalone receipt-validation subcommand. Receipt generation performs its internal
validation; consumers that need Draft 2020-12 validation use the repository schema separately.

## Exit codes

- `0`: the requested IssueProof operation completed successfully. A non-zero tested command may be
  preserved as reproduction evidence while IssueProof itself returns `0`.
- `2`: usage, option, or command parsing error.
- `3`: report, claims, schema, or trace validation error.
- `4`: missing dependency or unsafe output path.
- `5`: an executed command timed out.
- `6`: a handled internal or unexpected data error.

Receipt verdicts such as `refuted`, `unverified`, or `inconclusive` remain explicit evidence results;
they are not converted into a false successful-verification claim.

## Skill and plugin distribution

The wheel installs the Python package and `issue-proof` console entry point only. It does not
register the Codex Skill or plugin. The source checkout and source distribution contain:

- `skills\reproduce-github-issue\` — the complete Skill, references, agent metadata, and delegate
  script;
- `.codex-plugin\plugin.json` — a skills-only plugin manifest.

Keep the complete Skill directory when installing it independently; copying only `SKILL.md` omits
required references and the delegate script. The Skill and skills-only plugin require `issue-proof`
in the Python environment used to run the delegate. The delegate invokes that exact interpreter in
isolated mode with `-m issue_proof`; it does not search the checkout or `PATH` for an executable and
does not import repository source by path.

## CI and project status

CI runs on `windows-latest` for Python 3.11, 3.12, and 3.14. It checks formatting, lint, tests with
coverage, `codex doctor`, and package builds. The separate manual receipt-artifact workflow also runs
on Windows and consumes only explicitly selected artifacts from an explicit workflow run.

This is an early-stage community project. It has no telemetry and makes no claims about users,
downloads, adoption, partnerships, or official program eligibility.

## Contributing and license

See [`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/receipt-model.md`](docs/receipt-model.md), and
[`docs/roadmap.md`](docs/roadmap.md). Licensed under Apache-2.0; see [`LICENSE`](LICENSE).
