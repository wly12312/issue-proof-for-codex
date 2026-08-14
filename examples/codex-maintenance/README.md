# Offline Codex maintenance fixture

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

The two JSONL files in this directory are synthetic, recorded-compatible fixtures. They are not an
online Codex run, do not contain a real prompt or assistant transcript, and must not be presented as
OpenAI or user evidence. They exercise bounded retained trace projections, redaction, claims, and
receipt rendering. Trace input is still scanned and hashed in full.

`generate_fixture_repo.py` creates a disposable mini checkout containing a failing command, a local
Issue, and matching command-argv JSON. Creating `fixed.marker` simulates the smallest fix.

## Complete PowerShell walkthrough

Run this from the repository root after installing the development environment described in
`CONTRIBUTING.md`:

```powershell
$RepoRoot = (Get-Location).Path
$Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
$Fixture = Join-Path $RepoRoot '.issue-proof\codex-fixture'
$Trace = Join-Path $RepoRoot 'examples\codex-maintenance\trace-order-a.jsonl'
$Claims = Join-Path $RepoRoot 'examples\codex-maintenance\claims.json'

if (Test-Path -LiteralPath $Fixture) {
    throw "The fixture directory already exists: $Fixture"
}

& $Python '.\examples\codex-maintenance\generate_fixture_repo.py' --output $Fixture
$env:PATH = "$(Split-Path $Python);$env:PATH"

Push-Location $Fixture
try {
    & $Cli collect `
        --issue-file '.\issue.md' `
        --command-argv '.\baseline-command.json' `
        --output '.\baseline-1' `
        --repo-root '.' `
        --identity-mode github

    & $Cli collect `
        --issue-file '.\issue.md' `
        --command-argv '.\baseline-command.json' `
        --output '.\baseline-2' `
        --repo-root '.' `
        --identity-mode github

    New-Item -ItemType File -Path '.\fixed.marker' -Force | Out-Null

    & $Cli verify `
        --baseline '.\baseline-1\report.json' `
        --command-argv '.\verify-command.json' `
        --output '.\verified' `
        --repo-root '.' `
        --identity-mode github
    & $Cli receipt `
        --baseline '.\baseline-1\report.json' `
        --baseline '.\baseline-2\report.json' `
        --verification '.\verified\report.json' `
        --issue-file '.\issue.md' `
        --repo-root '.' `
        --identity-mode github `
        --output '.\receipt'

    # Optional trace enrichment; it does not replace the core reports above.
    & $Cli receipt `
        --baseline '.\baseline-1\report.json' `
        --baseline '.\baseline-2\report.json' `
        --verification '.\verified\report.json' `
        --issue-file '.\issue.md' `
        --repo-root '.' `
        --identity-mode github `
        --trace $Trace `
        --claims $Claims `
        --output '.\receipt-with-trace'
}
finally {
    Pop-Location
}
```

The baseline command exits non-zero until `fixed.marker` exists. The generated
`verify-command.json` contains the same argv, so `verify` executes an independent matching command.
The top-level `receipt` command combines both baseline reports and the verification report; the
first receipt is valid without a trace, while the second demonstrates optional trace enrichment.

Inspect the actual generated fields instead of comparing timestamps, IDs, or hashes with a copied
sample:

```powershell
$Receipt = Get-Content `
    -Raw `
    -Encoding utf8 `
    -LiteralPath '.\.issue-proof\codex-fixture\receipt\receipt.json' |
    ConvertFrom-Json

$Receipt.verdict
$Receipt.baseline.outcome
$Receipt.verification.outcome
$Receipt.verification.baseline_report_sha256
$Receipt.checks | Select-Object id, outcome, status
$Receipt.claims | Select-Object id, type, status, evidence_ids
```

For compatibility testing only, the older `codex verify` command still accepts one baseline and an
explicit trace. It is not the Skill's main workflow.

To inspect trace parsing alone without executing verification:

```powershell
$Cli = (Resolve-Path '.\.venv\Scripts\issue-proof.exe').Path
& $Cli codex ingest `
    --trace '.\examples\codex-maintenance\trace-order-a.jsonl' `
    --output '.\.issue-proof\codex-ingest'
```

The fixture stores no real credential: token-shaped text exists only to verify redaction.
