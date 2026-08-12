# Codex integration

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

IssueProof is a downstream evidence layer. It does not launch Codex, submit prompts, make an OpenAI
API request, or inspect Codex private local state. A maintainer explicitly supplies an existing
JSONL trace.

## Trace ingestion

From a Windows source checkout with the CLI installed:

```powershell
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
& $Cli codex ingest `
    --trace '.\codex-run.jsonl' `
    --output '.\.issue-proof\codex-run'
```

The parser streams the supplied path once. It hashes the source bytes, bounds line/event/text
capture, reports corrupt lines, counts unknown event types, and sanitizes projected evidence. It
does not copy the raw trace. Unknown events are not positive evidence; parse errors and event-limit
truncation make a receipt inconclusive.

Use `--strict` when the import must stop at the first invalid line. When generating a receipt with
`codex receipt` or `codex verify`, use `--include-messages` only after an explicit privacy decision;
message content remains bounded and sanitized. `codex ingest` has no message-content option.

## Draft a receipt without executing verification

```powershell
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
& $Cli codex receipt `
    --trace '.\codex-run.jsonl' `
    --issue-file '.\issue.md' `
    --baseline '.\.issue-proof\baseline\report.json' `
    --repo-root '.' `
    --claims '.\claims.json' `
    --output '.\.issue-proof\receipt'
```

This command imports the trace and existing evidence; it does not run the baseline or an independent
verification command. A supplied baseline alone cannot support `fix-verified`.

## Run independent verification

First create a generic baseline with an explicit failing command. Then store the same argv in JSON:

```json
{
  "argv": ["pytest", "tests\\test_bug.py", "-q"]
}
```

Run verification from PowerShell:

```powershell
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
& $Cli codex verify `
    --baseline '.\.issue-proof\baseline\report.json' `
    --trace '.\codex-run.jsonl' `
    --command-argv '.\verify-command.json' `
    --repo-root '.' `
    --claims '.\claims.json' `
    --output '.\.issue-proof\verified'
```

`codex verify` executes the explicit argv with the current Windows user's permissions. That program
may access the network, modify files, or spawn processes; IssueProof does not sandbox it. A verified
outcome requires a completed reproduced baseline, matching argv, a non-timeout verification, and
exit code zero.

## Public and experimental boundaries

The adapter recognizes the documented outer `thread.*`, `turn.*`, `item.*`, and `error` event
families and locally tested projections of command, file-change, tool, and message items. Nested
payload layouts are treated as version-sensitive. The receipt records the adapter as
`experimental-compatible`, counts unfamiliar events, and never treats an assistant narrative as
independent proof.

The implementation does not claim compatibility with private rollout files, application databases,
hidden reasoning, undocumented session formats, or Codex home/history/configuration.

## Repository instructions

Repository-scoped AGENTS provenance can be inspected without reading Codex home state:

```powershell
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
& $Cli codex agents --repo '.' --target '.\src\issue_proof\cli.py'
```

The result is best-effort metadata: relative path, digest, size, effective directory scope,
readability, and warnings. Full content requires `--include-content` and remains bounded and
sanitized. It is not a reconstruction of Codex's hidden prompt assembly.

## Publishing boundary

Receipts are local drafts for maintainer review. The CLI does not post to GitHub, create or merge a
pull request, push commits, publish a release, or start a paid task. Any later sharing is a separate,
explicit maintainer action.
