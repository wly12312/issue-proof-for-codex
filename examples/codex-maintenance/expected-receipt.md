# Codex maintenance receipt expectations

This is a field guide for the synthetic fixture, not a copied real receipt and not evidence from an
online Codex task.

After completing the PowerShell walkthrough in this directory, inspect the generated
`verified\receipt.json` and `verified\receipt.md`. The receipt should explain, using that run's
actual values:

- the source trace SHA-256 and `experimental-compatible` adapter label;
- the reproduced baseline and matching independent verification command;
- claim statuses with receipt evidence IDs;
- repository and AGENTS provenance availability;
- warnings, redactions, unknown events, and parse errors;
- the final conservative verdict;
- that the raw trace and hidden reasoning were not persisted.

UUIDs, timestamps, hashes, command durations, and environment-dependent Git facts must come from
the generated receipt. Do not copy placeholder values into a report or present the synthetic trace
as real maintenance evidence.
