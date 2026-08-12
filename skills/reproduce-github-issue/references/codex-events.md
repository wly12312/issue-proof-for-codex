# Codex event adapter reference

The official Codex CLI documentation describes `codex exec --json` as a JSONL stream and documents
outer event families such as `thread.*`, `turn.*`, `item.*`, and `error`. It gives examples for
thread start, command execution item, agent message item, and turn completion. Nested item payloads
are not treated as a permanent schema here.

Use the adapter as follows:

- Strongly type only the documented outer event/type strings and locally tested projections.
- Keep command evidence separate from tool calls, file changes, and messages.
- Never persist raw prompt, assistant reasoning, tool arguments, stdout, or stderr without sanitizing
  and bounding it.
- Count unknown events and preserve only type/key metadata.
- In lenient mode, continue after a corrupt line with its line number; strict mode stops.
- Treat this adapter as `experimental-compatible` and inspect receipt warnings before relying on it.

Official references:

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/developer-commands?surface=cli
