# Start A New Codex Desktop Chat

Use this when opening a new Codex Desktop chat for this project.

## Workspace Folder

Open the new chat with this exact working directory:

```text
/Users/burhanhalilov/code/investment-tool
```

Do not use the data folder as the workspace.

## Runtime Data Folder

Runtime data is stored outside the code repo:

```text
/Users/burhanhalilov/investment-tool-data
```

The main X thread index is:

```text
/Users/burhanhalilov/investment-tool-data/x_threads/indexes/index.html
```

## What To Tell The New Chat

Paste this into a fresh Codex chat if it needs orientation:

```text
Work in /Users/burhanhalilov/code/investment-tool.
Do not use Google Drive as the live code or data workspace.
Runtime data is in /Users/burhanhalilov/investment-tool-data.
The .env file is in the repo and contains private API credentials; do not print it.

Before changing workflow or AI/vector behavior, read:
- docs/pipeline-orchestrator-plan.md
- docs/ai-vector-pass-design.md
- docs/storage-layout.md

The approved public workflow interface is being moved to:
- investment-tool workflow update|sync|refresh
- investment-tool workflow rebuild --stage <stage>
- investment-tool workflow check|doctor

The current direct X capture commands are transitional implementation details, not the final workflow design.
X capture never runs thread AI.
Phase 1 thread AI has no vector search.
Vector push/search design is postponed.
```

## Source-Of-Truth Docs

| File | Purpose |
| --- | --- |
| `docs/pipeline-orchestrator-plan.md` | Current non-AI workflow/orchestrator spec |
| `docs/ai-vector-pass-design.md` | Current postponed AI/vector design |
| `docs/storage-layout.md` | Code/data storage map |
| `README.md` | Short project overview |

## Current Important Code

| File | Purpose |
| --- | --- |
| `src/investment_tool/pipeline_orchestrator.py` | Transitional top-level runner; workflow command group is planned here |
| `src/investment_tool/capture_threads.py` | Compatibility wrapper for old X capture commands |
| `src/investment_tool/x_capture_job.py` | Live X capture stage; no thread AI/vector/market/HC work |
| `src/investment_tool/x_thread_store.py` | X cached JSON/HTML lifecycle and repair helpers |
| `src/investment_tool/x_raw_rebuild.py` | Rebuild X generated JSON from saved raw API |
| `src/investment_tool/x_capture_metadata.py` | Non-AI title, preview, ticker, and pending metadata helpers |
| `config/ticker_registry.json` | Ticker aliases and canonical ticker mapping |
| `config/owned_positions.json` | Owned tickers for index highlighting |
| `.env` | Private credentials |

## Rules To Preserve

- Keep code in `/Users/burhanhalilov/code/investment-tool`.
- Keep data in `/Users/burhanhalilov/investment-tool-data`.
- Do not print or commit `.env`.
- Do not move live data into Google Drive.
- Only copy final reports to Google Drive if explicitly requested.
- Read the two spec docs before implementing workflow or AI/vector changes.
