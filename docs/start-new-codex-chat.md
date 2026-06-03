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
Main script: src/investment_tool/capture_threads.py.
Run command: PYTHONPATH=src python3 -m investment_tool.capture_threads
Main index: /Users/burhanhalilov/investment-tool-data/x_threads/indexes/index.html.
User prefers plain language, HTML reports, no YAML, and step-by-step explanations.
```

## Normal Run

From `/Users/burhanhalilov/code/investment-tool`:

```bash
PYTHONPATH=src python3 -m investment_tool.capture_threads
```

Cheap smoke test:

```bash
PYTHONPATH=src python3 -m investment_tool.capture_threads --max-threads 1 --timeline-pages 1 --conversation-pages 1 --no-analyze
```

## Important Files

| File | Purpose |
| --- | --- |
| `README.md` | Short project overview |
| `docs/storage-layout.md` | Code/data storage map |
| `docs/ai_storage_infographics.html` | Visual explanation of stored data |
| `src/investment_tool/capture_threads.py` | Main X capture, render, and AI analysis script |
| `config/ticker_registry.json` | Ticker aliases and canonical ticker mapping |
| `config/owned_positions.json` | Owned tickers for index highlighting |
| `.env` | Private credentials |

## Rules To Preserve

- Keep code in `/Users/burhanhalilov/code/investment-tool`.
- Keep data in `/Users/burhanhalilov/investment-tool-data`.
- Do not print or commit `.env`.
- Do not move live data into Google Drive.
- Only copy final reports to Google Drive if explicitly requested.
- AI analysis runs after a full X thread is compiled, not for every single reply.
- Routine X token refresh should be quiet unless it fails.
