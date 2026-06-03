# Start A New Codex Desktop Chat

Use this when opening a new Codex Desktop chat for this project.

## Workspace Folder

Open the new chat with this exact working directory:

```text
/Users/burhanhalilov/code/investment-tool
```

Do not use the data folder as the workspace.

## Data Folder

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
Top-level runner: src/investment_tool/pipeline_orchestrator.py.
X capture compatibility wrapper: src/investment_tool/capture_threads.py.
Run command: PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-capture
Main index: /Users/burhanhalilov/investment-tool-data/x_threads/indexes/index.html.
User prefers plain language, HTML reports, no YAML, and step-by-step explanations.
```

## Normal Run

From `/Users/burhanhalilov/code/investment-tool`:

```bash
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-capture
```

Cheap smoke test:

```bash
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-capture --max-threads 1 --timeline-pages 1 --conversation-pages 1
```

## Important Files

| File | Purpose |
| --- | --- |
| `README.md` | Short project overview |
| `docs/storage-layout.md` | Code/data storage map |
| `docs/ai_storage_infographics.html` | Visual explanation of stored data |
| `src/investment_tool/pipeline_orchestrator.py` | Top-level stage and maintenance runner |
| `src/investment_tool/capture_threads.py` | Compatibility wrapper for old X capture commands |
| `src/investment_tool/x_capture_job.py` | Live X capture stage; no AI/vector/market work |
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
- X capture never runs AI. AI analysis runs in separate pipeline stages after a full thread/media context is compiled.
- Routine X token refresh should be quiet unless it fails.
