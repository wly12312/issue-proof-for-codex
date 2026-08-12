# Offline Codex maintenance fixture

These files are synthetic, recorded-compatible JSONL examples. They are not an online Codex run,
do not contain a real prompt or assistant transcript, and must not be presented as evidence from
OpenAI. They exercise the offline trace adapter, redaction, claims, and receipt rendering.

`generate_fixture_repo.py --output PATH` creates a disposable mini repository with a failing
baseline command, issue file, and explicit command-argv files. Create `fixed.marker` in that fixture
to simulate the fix and run the same command for independent verification.

The two JSONL files use two legal orderings of the same small event vocabulary. Run
`issue-proof codex ingest --trace trace-order-a.jsonl --output .issue-proof/codex-run` from the
repository root to inspect one without starting Codex.
