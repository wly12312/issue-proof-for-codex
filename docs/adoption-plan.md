# Adoption plan

This plan records whether the Codex maintenance receipt is useful without inventing usage data or
uploading user evidence.

## Staged route

1. Dogfood on this repository's own Issues. Attach local receipts to development notes only after
   sanitization and explicit review.
2. Ask a small number of active OSS projects for permission to trial one or two Codex-assisted
   maintenance issues. Provide a local-only workflow and let each maintainer keep or delete the
   bundle.
3. Compare the workflow with ordinary triage, a human-only fix, and any existing agent process.
   Record limitations, false confidence, and time saved, not marketing claims.

## Metrics and collection

| Metric | Definition | Collection method | Default privacy behavior |
| --- | --- | --- | --- |
| Receipts generated | Count of locally generated receipts | Maintainer aggregate or fixture audit | Never upload raw receipts by default |
| Repositories adopting | Distinct repositories that voluntarily run the workflow | Maintainer-maintained local count | Hash or coarse-label identities if shared |
| Claims supported/unverified/refuted | Counts by receipt claim status | Recompute from reviewed receipt JSON | No telemetry or hidden collection |
| Bugs reproduced before fix | Receipts with a supported `bug-reproduced` claim | Local receipt review | Keep Issue content out of aggregate logs |
| Fixes independently verified | Receipts with supported `fix-verified` and verified verdict | Local receipt review | Do not infer causality |
| Maintainer review time saved | Voluntary before/after estimate | Coarse local time log | Never require personal data |
| External Issues, PRs, contributors | Accepted public contributions and fixtures | Git history and project records | Do not infer identity from evidence |
| Release/adoption cadence | Time between tagged releases or review checkpoints | Maintainer notes | No automated upload |

These are realistic OSS operating indicators, not official Codex, OpenAI, or program eligibility
criteria. Thresholds should be chosen after several reviewed trials; no threshold is claimed here.

Any future telemetry would require explicit opt-in, documentation, and a separate privacy review.
