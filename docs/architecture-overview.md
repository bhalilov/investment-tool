# Architecture Overview

This is the high-level map of the investment-tool system as it exists today and
where the next major pieces fit.

## Product Goal

Build a local investment research brain that preserves messy source evidence,
adds dated context, and prepares clean evidence for later AI analysis,
retrieval, portfolio/timeline reconstruction, and external interfaces.

The system should support:

- routine 15-minute incremental capture;
- manual/historical rebuilds;
- expensive AI passes only when explicitly staged;
- human QA through local HTML/indexes;
- future MCP and Custom GPT/API access over the same evidence.

## Layers

```text
External sources
  -> feeds/            capture/import original material
  -> context/          dated supporting evidence
  -> analysis/         expensive AI interpretation
  -> retrieval/        future vector/search memory
  -> interfaces/       future MCP, Custom GPT APIs, app connectors
  -> presentation/     local human QA views
```

`workflow/` coordinates these layers. It should not own the feed-specific,
AI-specific, or interface-specific implementation.

## Current Implemented System

Implemented feeds:

- X API capture and raw rebuild;
- saved article archive ingest;
- manual screenshot bundle import/reconstruction.

Implemented context:

- USD-normalized market prices;
- neutral media descriptions/OCR for downloaded images.

Implemented presentation:

- local X thread HTML pages;
- indexes with browser-side dynamic decoration.

Implemented shared runtime:

- env loading;
- path resolution;
- config/rule/model registries;
- job reporting;
- OpenAI JSON helper.

## Current Package Boundaries

```text
src/investment_tool/
├── cli/          command entrypoints only
├── workflow/     orchestration, locks, logs, checks
├── runtime/      env, config, paths, reporting
├── feeds/        source capture/import
├── context/      prices and media descriptions
├── analysis/     OpenAI helpers and future AI passes
├── retrieval/    future vector/search memory
├── interfaces/   future MCP, Custom GPT API, external access
├── presentation/ HTML/index rendering
├── rules/        feed-neutral ticker/filtering logic
└── records/      future explicit record models
```

Design rule: shared helpers stay in their owning package. Interface modules
adapt shared capabilities; they should not duplicate capture, storage,
analysis, config, path, or reporting logic.

## Runtime Data Boundary

Runtime data lives outside Git at `<data>`. The local machine path is recorded
in the workspace-level `HANDOFF.md`, not in repo-tracked specs.

Canonical storage mirrors the code concepts:

```text
<data>/
├── feeds/
├── context/
├── presentation/
├── retrieval/
└── workflow/
```

Runtime files are evidence/output, not source code. Do not commit them.

## Workflow Model

Normal production sync:

```text
x-capture -> screenshots -> descriptions -> render
```

Prices are not part of the 15-minute sync cycle. Run prices explicitly on a
separate cadence.

Manual rebuild/maintenance stages include:

```text
x-raw
x-reindex
x-repair-media-paths
x-recover-media
prices
articles
render
check / doctor
```

## AI And Retrieval Direction

Current design decisions:

- X capture does not run thread AI.
- Capture does not push vectors.
- Media descriptions run before thread AI as neutral visual evidence.
- Phase 1 thread AI has no vector retrieval.
- Phase 1 should produce clean dated evidence.
- Phase 2 may use vector retrieval after Phase 1 evidence exists.
- Retrieval must be time-aware; vector memory is recall, not source of truth.

Future evidence should support:

- timeline events;
- answered questions;
- portfolio/action clues;
- tone/sarcasm/confusion markers;
- linked-context needs;
- human corrections.

## External Interfaces Direction

Future external access belongs under:

```text
src/investment_tool/interfaces/
```

Planned interface families:

- `interfaces/mcp/` for MCP server/protocol access;
- `interfaces/custom_gpt/` for Custom GPT/API/action experiments;
- future local APIs or app connectors.

Interfaces should query shared records/context/retrieval APIs. They should not
reimplement feed capture or analysis pipelines.

## Current Worktree Strategy

```text
core/          main
mcp/           feat/mcp-investing-brain
custom-gpt/    feat/custom-gpt-api
ai-pass1/      feat/ai-pass1
architecture/  docs/architecture-brain-design
```

Use `architecture/` for high-level design and docs. Use feature worktrees for
implementation. Merge accepted shared foundations to `main` before multiple
features depend on them.

## Known Documentation Drift To Fix

- Some backlog entries describe work already completed and should be split into
  “done/history” versus “active backlog.”
- Screenshot reconstruction still needs a canonical thread-record path.
- Retrieval v2 remains intentionally unimplemented.
