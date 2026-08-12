# Contributing

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

Changes must preserve this Windows-only boundary. Do not add Linux, macOS, POSIX process-control,
or non-Windows workflow branches as part of an ordinary maintenance change.

## Development environment

Use PowerShell and one of the tested Python versions. Python 3.12 is a suitable default:

```powershell
py -3.12 -m venv .venv
$Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $Python -m pip install -e '.[dev]'
& $Python -m issue_proof doctor
```

The explicit interpreter path avoids depending on PowerShell activation policy and keeps every
command in the same virtual environment.

## Local quality gate

Run the checks from the repository root:

```powershell
$Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $Python -m ruff format --check .
& $Python -m ruff check .
& $Python -m pytest --cov=issue_proof --cov-report=term-missing
& $Python -m issue_proof codex doctor
& $Python '.\skills\reproduce-github-issue\scripts\run_issue_proof.py' doctor
& $Python -m build
git diff --check
```

The tests use synthetic, explicitly labeled Codex fixtures. They do not require a Codex task, an
API key, Docker, or network access. Tests for GitHub URL collection replace `gh` at the dependency
boundary; use a real authenticated `gh` only for an intentional manual check.

Before sharing a package change, also install the newly built wheel in a clean Windows virtual
environment whose path contains a space or Unicode character, then check `--version`, `doctor`, and
the Skill delegate. Report any skipped Windows symlink, reparse-point, or process-tree test with its
actual system error; do not count a permission-based skip as a pass.

## Change expectations

- Reproduce a defect before changing behavior. Add a regression test that fails for the reproduced
  defect and passes after the smallest practical fix.
- Preserve the existing CLI commands, exit-code meanings, report fields, receipt fields, schema
  versions, deterministic rendering, and privacy defaults unless the change explicitly addresses a
  confirmed contract defect.
- Keep command execution argv-based with `shell=False`. Preserve explicit empty arguments, Windows
  drive and UNC paths, Unicode and spaces, output-boundary checks, symlink/reparse-point guards,
  `taskkill /T /F`, timeout handling, and parent-process fallback.
- Treat missing, corrupt, truncated, or over-limit evidence conservatively. A Codex narrative is not
  independent verification.
- Keep Codex integration optional. Do not read private Codex state, start a Codex task, require an
  OpenAI API, or add telemetry.
- Keep the Skill self-contained: all relative references must stay inside its directory, and its
  delegate must call a separately installed CLI rather than importing repository source by path.
- Keep the plugin skills-only unless a separately reviewed change explicitly alters the product
  scope.
- Never commit credentials, raw private Issue data, real traces, generated evidence bundles,
  virtual environments, caches, build artifacts, or user-specific absolute paths.

## Documentation

Use executable PowerShell examples with Windows paths. Clearly distinguish IssueProof's own offline
parsing from an explicitly authorized command, which may access the network or modify files. Do not
publish fabricated usage, adoption, test, trace, or receipt results.

Whenever support is mentioned, use the exact three-line support boundary above. Keep normalized
JSON, Git, URL, and Markdown-link separators unchanged where `/` is part of the data format rather
than a platform command.
