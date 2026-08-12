# Research and architecture decisions

This is a deliberately bounded research pass for the Codex-first maintenance evidence layer. Links
and local CLI output were checked on 2026-08-12; the implementation keeps only findings that affect
the repository shape and safety model.

## Codex interface verification (2026-08-12)

- The local installation is `codex-cli 0.147.0`, found through the Windows `codex.cmd` launcher.
  `codex --help` and `codex exec --help` were read only; no task, login, API request, or quota-consuming
  run was started.
- The official [Codex non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
  defines `codex exec` for scripts/CI, documents read-only as the default sandbox, and documents
  `--sandbox`, `--output-last-message`, `--output-schema`, `--ephemeral`, and `--json`.
- The same official page documents JSONL stdout with outer event families such as `thread.*`,
  `turn.*`, `item.*`, and `error`; its sample includes `thread.started`, `item.started` with a
  `command_execution` item, `item.completed` with an `agent_message`, and `turn.completed` usage.
  The page does not promise that every item payload is a permanent schema. IssueProof therefore
  uses a tolerant streaming adapter: documented outer/event-family fields are strong evidence;
  item payload projections are explicitly `experimental-compatible` and unknown fields are not
  treated as proof.
- The official [developer command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
  confirms that `codex exec` is a stable non-interactive command and lists the machine-readable and
  sandbox flags. It also states that command flags and maturity labels can evolve, so the adapter
  records the observed CLI version when it is present in the trace instead of assuming a fixed
  local installation.
- The official [AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
  describes global and project-scope discovery, `AGENTS.override.md` precedence, root-to-target
  merge order, fallback filenames, and a default 32 KiB project instruction limit. IssueProof
  reports repository-scoped files only, does not read Codex home/history/config, and labels its
  result best-effort rather than claiming exact Codex internals.
- Official references for [Git worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees),
  [sandboxing](https://learn.chatgpt.com/docs/sandboxing), and the [Codex GitHub Action](https://learn.chatgpt.com/docs/github-action)
  were checked as safety/context references. This repository does not invoke the action, create a
  worktree, change approvals, post comments, open pull requests, or publish artifacts.

### Resulting compatibility boundary

The generic `issue-proof collect`, `verify`, `validate`, `render`, and `doctor` commands remain
unchanged in purpose and do not import or require a Codex installation. The optional `issue-proof
codex ...` layer reads only an explicitly supplied trace, uses no OpenAI API or paid task, stores a
trace digest rather than raw JSONL, and downgrades conclusions on corrupt lines, missing baseline
evidence, unsupported event types, or conflicting claims.

## Agent Skills and Codex plugins

- The [Agent Skills specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)
  defines a skill directory with a required `SKILL.md`, YAML frontmatter containing `name` and
  `description`, and optional `scripts/`, `references/`, and `assets/` directories. The skill uses
  only the required frontmatter keys, keeps the body short, and links its two reference files
  directly.
- [Plugins in Codex](https://help.openai.com/en/articles/20001256-plugins/) describes plugins as
  bundles that can contain skills and optional connected capabilities. This project is skill-only
  and does not declare an app or MCP dependency.
- The local official `skill-creator` and `plugin-creator` templates were used for initialization.
  The corresponding public reference is the [OpenAI skills plugin-creator guide](https://github.com/openai/skills/blob/main/skills/.system/plugin-creator/SKILL.md).
  The plugin manifest is kept at `.codex-plugin/plugin.json`; the skill lives under `skills/`.
- The local `init_skill.py` created the initial skill directory. Its YAML generator could not run
  because this machine does not have `PyYAML`; `agents/openai.yaml` therefore follows the same
  documented structure and is checked by an equivalent local validator in the test suite.

## Related tools and approaches

- Ordinary GitHub issue triage tools organize labels, severity, ownership, and summaries. They do
  not generally preserve a replayable command, sanitized logs, runtime facts, and hashes as one
  portable bundle.
- [Relunar](https://relunar.com/) is a close product comparison: it emphasizes reproducing issues
  from agent workflows and keeping evidence locally. `oss-issue-proof` is intentionally smaller,
  model-independent, CLI-first, and stores a versioned JSON/Markdown contract that can be used by
  humans, CI, or another agent.
- Research such as [SWE-Tester](https://arxiv.org/abs/2601.13713) and
  [Issue2Test](https://arxiv.org/abs/2503.16320) studies generating reproducing tests from issue
  reports. This MVP does not generate fixes or tests; it records and verifies a command explicitly
  chosen by the user.
- The skill creator's `quick_validate.py` and the plugin creator's `validate_plugin.py` are the
  intended structural validators. The former could not import `yaml` in this environment, so the
  repository also checks frontmatter keys, naming, line count, UI metadata, and plugin JSON shape.

## Name check

Direct checks of [PyPI oss-issue-proof](https://pypi.org/project/oss-issue-proof/) and
[PyPI issue-proof](https://pypi.org/project/issue-proof/) returned 404 at the time of research.
Search-engine results did not surface an active repository with either exact name; GitHub's direct
search endpoint was rate-limited during the check. This is not a trademark or namespace guarantee.
The required directory name is retained. A future release should re-check registries before
choosing a distribution name; `oss-issue-proof` remains the natural candidate for now.

## Architecture decisions

1. Use only the Python standard library for the runtime package. `argparse`, dataclasses, JSON, and
   `subprocess` avoid an OS-specific runtime dependency. Version 0.1.2 formally supports Windows
   10/11 only and is tested with Python 3.11, 3.12, and 3.14; retained Linux/macOS branches are
   unsupported, untested, and unverified.
2. Execute only an explicitly supplied command after parsing it into an argv array. Never pass the
   issue body, README, or logs to a shell. An explicit URL fetch is limited to the user's `gh`
   command and remains a separate dependency boundary.
3. Sanitize output before it is stored, cap each stream, and hash the sanitized bytes. Reports keep
   enough metadata for auditability while treating secrets as higher priority than raw logs.
4. Keep verification conservative: it requires a baseline reproduced outcome, a matching argv, a
   non-timeout run, and a clear current exit result. A single baseline run is reported as such and
   is not advertised as a sandbox or a proof of causality.
5. Write generated files only inside the requested output directory. The collector does not modify
   repository source files and copies only a sanitized issue snapshot into the evidence directory.
