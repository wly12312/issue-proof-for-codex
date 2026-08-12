# Generic report expectations

This is an interpretation guide, not the output of a real user run. An actual invocation generates
its own UUID, timestamps, repository revision, bounded sanitized output, and SHA-256 values.

For the deterministic example in the root README:

- the baseline report records `reproduction.outcome` as `reproduced` because the explicit command
  completes with a non-zero exit before the marker exists;
- the baseline report records `verification.outcome` as `not-applicable`;
- the post-marker report records `verification.outcome` as `verified` only when the same argv
  completes with exit code zero;
- `report.md` is a deterministic rendering of the corresponding `report.json` fields, apart from
  values already generated for that run.

Use the exact PowerShell walkthrough in the root `README.md` to generate and validate the files.
Do not use this document as a golden receipt or claim that its prose is execution evidence.
