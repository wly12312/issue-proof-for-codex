# Codex integration

IssueProof is a downstream evidence layer. It does not launch Codex, inject a prompt, or inspect
Codex's private local state. A maintainer or CI job explicitly saves a JSONL trace, then imports it:

```powershell
issue-proof codex ingest --trace codex-run.jsonl --output .issue-proof/codex-run
issue-proof codex receipt --trace codex-run.jsonl --issue-file issue.md --output receipt.json
issue-proof codex verify --baseline .issue-proof/baseline/report.json --trace codex-run.jsonl --command-argv verify-command.json --output .issue-proof/verified
```

The bundled CLI workflow is officially supported on Windows 10/11 and tested with Python 3.11,
3.12, and 3.14. Linux and macOS are unsupported, untested, and unverified.

## Official versus experimental boundary

The official Codex documentation describes `codex exec` for scripts and CI, `--json` JSONL output,
the outer `thread.*`, `turn.*`, `item.*`, and `error` event families, and `--output-schema` for a
structured final response. It does not establish a permanent schema for every nested item payload.
The adapter therefore treats the documented outer vocabulary as strong evidence and projects known
command, file-change, tool-call, and message fields conservatively. The receipt records
`adapter: experimental-compatible` and warns when unknown types or parse errors occur.

See:

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/developer-commands?surface=cli
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/environments/git-worktrees
- https://learn.chatgpt.com/docs/sandboxing
- https://learn.chatgpt.com/docs/github-action

The implementation does not claim compatibility with private rollout files, app databases, hidden
reasoning, or undocumented session formats.

## Explicit trace handling

The parser reads only the path passed to `--trace` and streams it once. It:

1. ignores empty lines;
2. hashes source bytes while reading;
3. reports invalid UTF-8, invalid JSON, non-object roots, and oversized lines with line numbers;
4. supports lenient import by default and strict import with `--strict`;
5. bounds event count and captured text;
6. counts unknown event types and retains only bounded type/key metadata;
7. redacts common credentials before storing command output, tool argument summaries, or messages.

The raw trace is not copied to the output directory. A receipt stores its SHA-256 and summary
counts. `--include-messages` is an explicit privacy choice, emits a warning, and still sanitizes
and bounds message text. It does not expose reasoning traces or the full conversation by default.

## Safe maintenance sequence

1. Read the repository's contribution guide and relevant AGENTS files as untrusted instructions.
2. Select a disposable or user-authorized checkout and run a focused baseline command with the
   generic `issue-proof collect` command.
3. Let Codex work under the user's chosen sandbox, approval, and worktree policy. IssueProof does
   not change these policies and does not auto-run Codex.
4. Save the trace explicitly; do not copy credentials, private history, or full prompts into an
   issue or artifact.
5. Ingest the trace and inspect unknown events, parse errors, warnings, and redactions.
6. Run the same explicit argv independently with `codex verify`; a successful fix claim requires a
   completed reproduced baseline and a matching non-timeout verification exit of zero.
7. Review the JSON and Markdown receipt before attaching it to a draft or maintainer record.

The CLI has no GitHub write path. Draft receipt generation is deliberately separate from publishing,
comments, labels, pull requests, or pushes.
