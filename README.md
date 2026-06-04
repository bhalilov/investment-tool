# investment-tool

Local monitoring and evidence-capture tool for configurable investment research
sources.

## Current Layout

- Code: `/Users/burhanhalilov/code/investment-tool`
- Runtime data: `/Users/burhanhalilov/investment-tool-data`
- Main X index: `/Users/burhanhalilov/investment-tool-data/x_threads/indexes/index.html`

Private data, raw API responses, screenshots, reports, logs, runtime data, and
secrets must stay out of Git.

## Source-Of-Truth Specs

Read these before changing workflow or AI/vector behavior:

- `docs/pipeline-orchestrator-plan.md` - approved non-AI workflow/orchestrator design.
- `docs/ai-vector-pass-design.md` - postponed thread AI/vector design decisions.
- `docs/storage-layout.md` - code/data storage map.
- `docs/start-new-codex-chat.md` - handoff notes for a fresh Codex chat.

Older Custom GPT/vector docs are reference material only when marked as
superseded by the new AI/vector design.

## Architecture Rules

- Product logic lives in `src/investment_tool/`.
- `scripts/` is only for thin compatibility launchers or disposable probes.
- Scheduled runs, manual runs, rebuilds, and production should use the same
  package logic with different flags.
- When a prototype becomes useful, move the logic into `src/investment_tool/`
  before relying on it.
- Source accounts, source-specific interpretation notes, reconstruction rules,
  media rules, model choices, and prompts live under `config/` and `prompts/`.

## Approved Workflow Interface

The planned public interface is:

```bash
investment-tool workflow update
investment-tool workflow sync
investment-tool workflow refresh

investment-tool workflow rebuild --stage market-prices
investment-tool workflow rebuild --all

investment-tool workflow check
investment-tool workflow doctor
```

`update`, `sync`, and `refresh` are aliases for the normal incremental workflow.
`check` and `doctor` are read-only inspection aliases in v1. `rebuild` requires
one or more `--stage` values or explicit `--all`.

The current code still has transitional direct commands while the workflow
orchestrator is being implemented.

## Important Boundaries

- X capture never runs thread AI.
- Phase 1 thread AI intentionally has no vector search.
- Vector push/search behavior is postponed until the AI/vector design is
  reviewed again.
- Rendering/indexing should be split from capture in the new workflow.
- HC/Ghost ingest is explicit/manual in workflow v1, not part of scheduled
  update.

## Verification Before Pushing

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m py_compile src/investment_tool/*.py scripts/*.py tests/*.py
```
