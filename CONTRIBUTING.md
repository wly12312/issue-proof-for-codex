# Contributing

## Development environment

Use Python 3.11 or newer and an editable install:

```text
python -m venv .venv
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate with `./.venv/Scripts/Activate.ps1`; on POSIX use
`source .venv/bin/activate`.

## Checks

Run the full local quality gate:

```text
ruff format --check .
ruff check .
pytest --cov=issue_proof --cov-report=term-missing
python -m build
python skills/reproduce-github-issue/scripts/run_issue_proof.py doctor
python -m issue_proof codex doctor
```

The repository's tests do not require Docker, a Codex task, an API key, or network access. Codex
fixtures are synthetic and explicitly marked as such. GitHub URL behavior is tested at the
dependency boundary; use a real authenticated `gh` only for an intentional manual check.

## Change expectations

- Keep the standard `src/` layout and Python 3.11 compatibility.
- Preserve stable report fields, exit codes, deterministic rendering, and safety tests.
- Keep Codex integration optional: do not import private Codex state, require a Codex installation,
  or add a paid API/runtime dependency.
- Add a regression test for security-sensitive changes, especially parsing, redaction, timeouts,
  output limits, trace limits, AGENTS path handling, and output-path validation.
- Never add real credentials, raw private Issue data, generated evidence bundles, `.venv`, caches,
  or user-specific paths to a commit.
- Keep pull requests focused and describe the actual commands used to validate them.
