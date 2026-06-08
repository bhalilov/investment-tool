# investment-tool

Local investment research pipeline for capturing configurable feeds, preserving
the raw evidence, enriching it with market/context data, and preparing it for
later AI analysis and retrieval.

This repo is the code and spec home. Runtime data lives outside Git.

## What This Tool Does

The tool is being built to monitor investment-research feeds over time and keep
the evidence usable for later analysis.

Current implemented feed families:

- X threads from configured accounts.
- Saved article archives.
- Manual screenshot thread bundles.

Current supporting context:

- USD-normalized daily market prices.
- Image/media descriptions as a separate context stage.
- Rendered local HTML pages and indexes for browsing/QA.

Postponed but designed separately:

- Expensive thread AI pass 1 and pass 2.
- Vector push/search memory.
- Portfolio/timeline reconstruction.
- UI-driven manual correction loops.

## Core Architecture

The code is organized around a simple rule: folder context carries meaning.
That means we use `feeds/x/api.py`, not names like `x_x_api.py`, and runtime
data uses `feeds/x/records`, not repeated old names like `x_threads/thread_json`.

Main package layout:

| Folder | Purpose |
| --- | --- |
| `cli/` | Public command entrypoints |
| `workflow/` | Top-level orchestration, checks, locks, logs |
| `runtime/` | Env loading, config loading, path resolution, reporting |
| `feeds/` | Feed-specific capture/ingest code |
| `context/` | Supporting context such as prices and image descriptions |
| `analysis/` | Shared OpenAI helpers and future AI passes |
| `retrieval/` | Future retrieval memory |
| `interfaces/` | Future external access surfaces such as MCP and Custom GPT APIs |
| `presentation/` | HTML thread pages and indexes |
| `rules/` | Feed-neutral parsing/filtering rules |
| `records/` | Canonical record shapes, as they become explicit |

Important design boundary:

- `workflow` coordinates.
- `feeds/*` capture or ingest feed data.
- `context/*` creates supporting data.
- `presentation/*` renders human-readable views.
- `analysis/*` and `retrieval/*` stay separate from capture.

## Runtime Data

Runtime data is referred to as `<data>`.

Resolution order:

1. Explicit `--data-dir`
2. `INVESTMENT_TOOL_DATA_DIR`
3. `INVESTMENT_TOOL_HOME/data`
4. Repo-local `data/`

Canonical runtime layout:

```text
<data>/
├── feeds/
│   ├── x/{raw,records,media,ignored,usage}
│   ├── articles/{archive,records,evidence,manifest.json}
│   └── screenshots/{inbox,bundles,media,records}
├── context/
│   ├── prices/{daily,hourly,intraday,manifest.json}
│   └── descriptions/{x,screenshots}
├── presentation/{threads/x,indexes}
├── retrieval/
└── workflow/{logs,locks}
```

Runtime folders include plain `README.md` descriptions so the data remains
scanable even without the code open.

Never commit runtime data, raw API responses, screenshots, logs, reports, or
secrets.

## Workflow Model

The public interface is `investment-tool workflow`.

Normal incremental aliases:

```bash
investment-tool workflow update
investment-tool workflow sync
investment-tool workflow refresh
```

Manual rebuilds:

```bash
investment-tool workflow rebuild --stage prices
investment-tool workflow rebuild --stage x-raw --stage render
investment-tool workflow rebuild --all
```

Read-only checks:

```bash
investment-tool workflow check
investment-tool workflow doctor
```

V1 scheduled update stage order:

1. `x-capture`
2. `screenshots`
3. `prices`
4. `descriptions`
5. `render`

`articles` and `x-raw` are explicit/manual stages in v1, not part of the normal
scheduled update.

## Current Rules

Project rules:

- Work from the repo, not from the runtime data folder.
- Product logic belongs under `src/investment_tool/`.
- `scripts/` is only for disposable probes.
- Useful prototype logic must move into `src/investment_tool/` before it becomes
  relied upon.
- Scheduled runs, manual runs, rebuilds, and production should use the same
  package logic with different flags.
- Configurable feed accounts, feed-specific interpretation notes, reconstruction
  rules, media rules, model choices, and prompts belong under `config/` and
  `prompts/`.
- Paths in docs/config/code should be portable: use `<repo>`, `<data>`, env
  variables, or relative project paths, not user-specific absolute paths.

Capture and analysis rules:

- X capture saves raw API, clean records, and photo media only.
- X capture does not run thread AI.
- X capture does not push vectors.
- Videos and animated GIFs are skipped as media-analysis inputs and represented
  with placeholders/tags.
- HTML/index rendering is a separate `render` stage.
- Phase 1 thread AI has no vector search.
- Phase 2 retrieval/vector behavior is postponed until the AI/vector spec is
  finalized.
- Legacy vector sync and the old Custom GPT action server have been deleted.
- Future retrieval/vector work must follow `docs/ai-vector-pass-design.md`.

Git rules:

- Major architecture changes and bug fixes should be committed on a branch.
- Commit messages should describe intent, not just file movement.
- Runtime data and `.env` stay out of Git.
- Before pushing, run compile/tests and relevant workflow checks.

## Important Specs

The README is the orientation layer. Detailed implementation decisions live in
docs and should be treated as the source of truth when changing that area.

| Spec | Use it for |
| --- | --- |
| `docs/pipeline-orchestrator-plan.md` | Workflow commands, stage order, logs, locks, scheduler model |
| `docs/ai-vector-pass-design.md` | Postponed thread AI/vector design, pass 1/pass 2 boundaries |
| `docs/code-organization-spec.md` | Package hierarchy and naming rules |
| `docs/storage-layout.md` | Runtime data layout and folder ownership |
| `docs/feed-record-spec.md` | Stored feed record shapes |
| `docs/x-reconstruction-spec.md` | X raw API to clean thread reconstruction |
| `docs/media-handling-spec.md` | Media ownership, skipped videos/GIFs, descriptions |
| `docs/market-data-spec.md` | Price universe and market-data behavior |
| `docs/presentation-spec.md` | HTML thread pages and indexes |
| `docs/run-reporting-spec.md` | Job status/reporting conventions |
| `docs/article-feed-spec.md` | Saved article archive ingest |
| `docs/screenshot-feed-spec.md` | Manual screenshot bundles and reconstruction |
| `docs/legacy-retrieval-note.md` | Deleted vector/evidence behavior and reusable mechanics |
| `docs/backlog.md` | Current implementation backlog |

## Verification

Run these before pushing code changes:

```bash
python3 -m py_compile src/investment_tool/*.py scripts/*.py tests/*.py
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m investment_tool.cli.main workflow check
```

No paid AI calls, X API calls, market data calls, or vector uploads should run
during normal documentation/code-structure verification.
