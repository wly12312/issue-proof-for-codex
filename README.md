# IssueProof for Codex

> IssueProof for Codex turns a Codex-assisted OSS maintenance run into an independently verifiable maintenance receipt.

`oss-issue-proof` is an independent community project that provides an evidence and verification
layer for Codex-powered open-source maintenance. It is not an OpenAI product, does not claim OpenAI
endorsement, and does not replace maintainer review.

## The maintenance loop

```text
Issue → baseline reproduction → Codex task → trace ingestion → independent verification → maintainer receipt
```

The result is a portable `CodexMaintenanceReceipt`: a versioned, redacted record of what can be
checked, what was observed, which claims are supported/refuted/unverified, and why the final verdict
was reached. It stores the SHA-256 of an explicitly supplied trace rather than the raw trace by
default. It never stores hidden reasoning, a full prompt, the full environment, Codex private state,
or an unbounded conversation.

## Using with Codex

The Codex layer is offline and needs no API key. It never starts Codex; it consumes a JSONL trace
that a user or CI job has already saved. With a local source checkout:

```text
python -m issue_proof codex doctor
python -m issue_proof codex ingest --trace codex-run.jsonl --output .issue-proof/codex-run
python -m issue_proof codex receipt --trace codex-run.jsonl --issue-url https://github.com/OWNER/REPO/issues/123 --output receipt.json
python -m issue_proof codex verify --baseline .issue-proof/baseline/report.json --trace codex-run.jsonl --command-argv verify-command.json --output .issue-proof/verified
```

`verify-command.json` contains an explicit argv array, not a shell string:

```json
{"argv": ["pytest", "tests/test_bug.py", "-q"]}
```

A five-minute offline walkthrough is under [`examples/codex-maintenance/`](examples/codex-maintenance/).
Its JSONL files are synthetic, recorded-compatible fixtures, not real online Codex tasks. The
fixture covers baseline failure, simulated file change, independent pass verification, redaction,
claims, and Markdown receipt shape.

The shortest offline check after installation is:

```text
issue-proof codex ingest --trace examples/codex-maintenance/trace-order-a.jsonl --output .issue-proof/codex-run
```

## What a real receipt looks like

```markdown
# Codex Maintenance Receipt

- Verdict: **verified**
- Trace SHA-256: `6f3e...`
- Baseline: **reproduced**
- Verification: **verified**
- Claims:
  - `fix-verified`: **supported** (evidence: `verification`)
  - `files-changed`: **supported** (evidence: `git-end`, `trace-files`)
- Raw trace, prompt, assistant reasoning, and private Codex state: **not persisted**
```

The full JSON contract is [`schemas/codex-maintenance-receipt.schema.json`](schemas/codex-maintenance-receipt.schema.json);
the model and evidence-ID rules are documented in [`docs/receipt-model.md`](docs/receipt-model.md).

## What this is not

| Workflow/tool | Difference from IssueProof |
| --- | --- |
| Issue triage | Triage organizes reports; IssueProof preserves reproducible command and verification evidence. |
| Autonomous auto-fix | Codex may be used separately to edit a checkout; IssueProof imports evidence and independently runs an explicitly authorized verification command. |
| Generic log collector | IssueProof has bounded redaction, Git/AGENTS provenance, baseline relation, claims, and a versioned verdict. |
| Codex Security | Security scanning and remediation are separate concerns; this project does not claim vulnerability coverage. |

It is not a sandbox. An explicitly authorized verification command may access the network, modify
files, or spawn processes; use a disposable checkout and OS-level isolation for untrusted code. It
does not post to GitHub, write comments, create pull requests, publish, push, or consume paid Codex
tasks. It does not replace human review, prove causality, or infer success from a narrative alone.

## Generic CLI (secondary mode)

The original model-independent commands remain available and do not require Codex:

```text
issue-proof doctor
issue-proof collect --issue-file issue.md --command "pytest tests/test_bug.py -q" --output .issue-proof/baseline
issue-proof validate .issue-proof/baseline/report.json
issue-proof render .issue-proof/baseline/report.json
issue-proof verify --baseline .issue-proof/baseline/report.json --command "pytest tests/test_bug.py -q" --output .issue-proof/verified
```

The generic report schema remains `1.0.0`; the optional `codex` object is additive and old reports
continue to validate and load. The package name, Python module, and `issue-proof` executable are
unchanged.

## Exit codes

Exit code `0` means IssueProof successfully wrote its report or receipt; a non-zero command result
is preserved as evidence rather than hidden. Usage and command parsing errors use `2`, schema or
trace errors use `3`, missing dependencies or unsafe output paths use `4`, timeouts use `5`, and
unexpected internal errors use `6`. A receipt with verification outcome `not-fixed` or
`inconclusive` is therefore an explicit negative or uncertain result even when the receipt itself
was written successfully.

## Install

Requires Python 3.11+.

```text
python -m venv .venv
Windows PowerShell: .\.venv\Scripts\Activate.ps1
POSIX shell: source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Runtime dependencies are standard-library only. Codex is optional and is detected only by the
read-only `issue-proof codex doctor` command; the receipt adapter also works when Codex is absent.

## Distribution model

The Python wheel distributes the `issue-proof` CLI and its runtime package only. The Codex Skill
and `.codex-plugin` manifest are installed from a repository checkout or another source bundle;
installing the wheel does not install the complete Codex Skill/plugin. Schemas, examples, tests,
and extended documentation remain source-repository artifacts rather than being mechanically added
to the wheel.

## Platform support

- Windows: locally exercised on Python 3.12; the symlink-specific provenance test is skipped when
  the host does not grant Windows symlink creation, and this limitation is reported rather than
  treated as a pass.
- Linux: included in the GitHub Actions matrix through `ubuntu-latest`; no local Linux run is
  claimed from this checkout.
- macOS: not exercised by this prerelease and not covered by the current workflow.

## Security and privacy defaults

- Only an explicitly supplied trace path is read. The adapter never scans `~/.codex`, app databases,
  session history, environment files, or home directories.
- JSONL is streamed with line/event/text limits. Empty lines are ignored; corrupt lines report their
  line number; strict mode stops at the first parse error; unknown event types are counted and reduced
  to type/key metadata.
- Command arguments, stdout/stderr, messages, Issue text, URLs, and AGENTS content are sanitized and
  bounded. Full messages require `--include-messages`, which prints a privacy warning and still
  stores only sanitized, bounded text.
- Repository-scoped AGENTS files are reported by relative path, hash, size, scope, and readability;
  full content is omitted unless explicitly requested. This is a best-effort mirror of documented
  scope, not a claim about Codex internals.
- Remote URLs are redacted, Git common-directory paths are represented by a digest, and raw prompts,
  hidden reasoning, full environment, and Codex config are excluded by default.

See [`docs/security-model.md`](docs/security-model.md) and [`SECURITY.md`](SECURITY.md).

## Skill and CI

The existing `reproduce-github-issue` Skill now guides Codex maintenance from baseline through
receipt, including downgrade conditions and draft-only boundaries. The normal CI validates the
package, schema, Skill, and offline fixtures on Ubuntu and Windows with Python 3.11 and the current
stable matrix entry. A separate manual workflow can consume uploaded trace/report artifacts from an
explicit source run ID and generate a receipt artifact with read-only `contents`/`actions` access; it
does not post comments or run `pull_request_target`.

## Project status and adoption

This is a community-maintained, early-stage project. It makes no claims about users, stars,
downloads, partnerships, official program eligibility, or OpenAI support. Adoption measurements are
voluntary, local, anonymized, and auditable; see [`docs/adoption-plan.md`](docs/adoption-plan.md).

## Contributing and license

See [`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/research.md`](docs/research.md), and
[`docs/roadmap.md`](docs/roadmap.md). Licensed under Apache-2.0; see [`LICENSE`](LICENSE).
