# Codex event adapter reference

## Support boundary

- Officially supported: Windows 10/11.
- Tested: Windows with Python 3.11, 3.12, and 3.14.
- Linux/macOS: unsupported, untested, and unverified.

The adapter imports an explicitly supplied `codex exec --json`-style JSONL stream. It recognizes
documented outer families such as `thread.*`, `turn.*`, `item.*`, and `error`, plus locally tested
projections of command, tool, file-change, and message items. Nested payloads are not assumed to be
a permanent schema.

Use these interpretation rules:

- Keep command evidence separate from tool calls, file changes, and messages.
- Sanitize and bound arguments, stdout, stderr, messages, paths, and metadata before persistence.
- Never treat an assistant message, tool-call narrative, or unknown payload as independent proof.
- Count unknown events and retain only bounded type/key metadata. Inspect them before relying on a
  receipt; they are not positive evidence.
- In lenient mode, continue after a corrupt line where possible and retain its line number. In
  strict mode, stop at the first parse error.
- Missing, corrupt, event-limit-truncated, or empty trace evidence cannot support a verified receipt.
- Treat the adapter label `experimental-compatible` as a version-compatibility warning.

Trace ingestion reads only the explicit path. It does not scan `$env:USERPROFILE\.codex`, start
Codex, make an OpenAI API request, or copy the raw JSONL into the output directory.
