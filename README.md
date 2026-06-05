# investment-tool

Local monitoring and evidence-capture tool for configurable investment research
sources.

## Current Layout

- Code: this repo checkout, referred to as `<repo>`
- Runtime data: `<data>`, resolved from `--data-dir`, `INVESTMENT_TOOL_DATA_DIR`,
  `INVESTMENT_TOOL_HOME/data`, or repo-local `data/`
- Main X index: `<data>/presentation/indexes/index.html`

Private data, raw API responses, screenshots, reports, logs, runtime data, and
secrets must stay out of Git.

## Source-Of-Truth Specs

Read these before changing workflow or AI/vector behavior:

- `docs/pipeline-orchestrator-plan.md` - approved non-AI workflow/orchestrator design.
- `docs/ai-vector-pass-design.md` - postponed thread AI/vector design decisions.
- `docs/code-organization-spec.md` - locked package hierarchy and naming.
- `docs/storage-layout.md` - code/data storage map.

## Architecture Rules

- Work from the code repo, not the runtime data folder.
- Product logic lives in `src/investment_tool/`.
- `scripts/` is only for thin compatibility launchers or disposable probes.
- Scheduled runs, manual runs, rebuilds, and production should use the same
  package logic with different flags.
- When a prototype becomes useful, move the logic into `src/investment_tool/`
  before relying on it.
- Source accounts, source-specific interpretation notes, reconstruction rules,
  media rules, model choices, and prompts live under `config/` and `prompts/`.
- Never print or commit private credentials from `.env`.

## Approved Workflow Interface

The public workflow interface is:

```bash
investment-tool workflow update
investment-tool workflow sync
investment-tool workflow refresh

investment-tool workflow rebuild --stage prices
investment-tool workflow rebuild --all

investment-tool workflow check
investment-tool workflow doctor

investment-tool storage migrate --dry-run
investment-tool storage migrate --apply
investment-tool storage migrate --verify-only
investment-tool storage clean-old --dry-run
investment-tool storage clean-old --apply
```

`update`, `sync`, and `refresh` are aliases for the normal incremental workflow.
`check` and `doctor` are read-only inspection aliases in v1. `rebuild` requires
one or more `--stage` values or explicit `--all`.

`storage migrate` is a rename/move cleanup for runtime data. It also writes
plain `README.md` descriptions into the main runtime folders so the data is
scanable without reading the code. After verification, `storage clean-old`
deletes obsolete migrated legacy folders and old staging files.

Direct stage commands still exist as compatibility launchers, but new
production work should start from the `workflow` command group.

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
