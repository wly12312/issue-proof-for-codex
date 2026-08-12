# Roadmap

## Codex-first maintenance evidence layer (current)

- Local Issue file and authenticated `gh` Issue URL input.
- Explicit argv execution with timeout, bounded sanitized logs, runtime/Git facts, stable hashes,
  JSON Schema contract, Markdown rendering, and conservative verification.
- Streaming, tolerant Codex JSONL import; versioned `CodexMaintenanceReceipt`; AGENTS and Git
  provenance; deterministic claims; offline baseline-to-trace-to-verify flow.
- Python CLI, Agent Skill, skill-only Codex plugin manifest, synthetic fixtures, tests, and CI matrix.

## 0.2

- Multiple-run stability sampling with explicit flakiness statistics.
- Optional artifact manifest for user-selected files, still bounded and path-checked.
- Better platform-specific process-tree diagnostics and richer `gh` authentication guidance.
- Schema migration tooling and machine-readable validation diagnostics.
- A compatibility fixture matrix for additional public Codex event releases, still offline and
  tolerant of unknown payloads.

## 0.3

- Pluggable language/runtime adapters for test discovery and version normalization.
- Maintainer-reviewed evidence comparison and signed local bundles.
- Optional integrations that remain opt-in and read-only by default.
- A documented, privacy-preserving aggregate format for voluntary adoption metrics.

## Later, only with a separate safety review

Docker or VM executors, a GitHub App, authorized comment write-back, and broader multi-language
environment provisioning are intentionally deferred. They are not implied by the CLI, receipt,
or Skill.
