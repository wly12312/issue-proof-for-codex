# Codex maintenance receipt expectations

This is a field guide for the synthetic fixture, not a copied real receipt and not evidence from an
online Codex task.

After completing the PowerShell walkthrough in this directory, inspect the generated
`receipt\receipt.json` and `receipt\receipt.md`. The no-trace receipt should explain, using that
run's actual values:

- the stable two-run baseline group and its report hashes;
- the reproduced baseline and matching independent verification command;
- the matching argv, cwd, repository, remote, HEAD, timeout, termination, runtime, and tool
  identity fields;
- the verification report's actual baseline SHA-256 and the receipt's recomputed identity relation;
- any additional checks with explicit `passed`, `failed`, or `inconclusive` status;
- claim statuses with receipt evidence IDs;
- repository and AGENTS provenance availability;
- warnings, including `trace-not-supplied`, redactions, unknown events, and parse errors;
- the final conservative verdict;
- that the core verdict does not require a trace.

The optional `receipt-with-trace` output additionally records the synthetic trace SHA-256 and
`experimental-compatible` adapter fields. It is enrichment, not a replacement for the core reports.

UUIDs, timestamps, hashes, command durations, and environment-dependent Git facts must come from
the generated receipt. Do not copy placeholder values into a report or present the synthetic trace
as real maintenance evidence.
