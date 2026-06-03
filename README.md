# investment-tool

Local monitoring and evidence-capture tool for configurable investment research sources.

Current local layout:

- Code: `/Users/burhanhalilov/code/investment-tool`
- Data: `/Users/burhanhalilov/investment-tool-data`
- Main X index: `/Users/burhanhalilov/investment-tool-data/x_threads/indexes/index.html`

Architecture rule:

- Product logic lives in `src/investment_tool/`.
- `scripts/` is only for thin compatibility launchers or disposable probes.
- Backfill, manual runs, scheduled runs, and production should use the same package logic with different flags.
- When a prototype becomes useful, move the logic into `src/investment_tool/` before relying on it.
- Source accounts, source-specific interpretation notes, reconstruction rules, media rules, model choices, and prompts live under `config/` and `prompts/`, not as account constants in code.

V1 priorities:

- Capture X posts, threads, media, screenshots, and OCR output reliably.
- Store all raw API responses locally.
- Use OpenAI analysis only after relevant thread context is compiled.
- Send alerts through local fallback, email, and Pushover when configured.
- Generate local HTML reports.

Private data, raw API responses, screenshots, reports, logs, database files, and secrets must stay out of Git.

The top-level orchestrator is `investment_tool.pipeline_orchestrator`. It controls pipeline stages and maintenance modes. X capture itself is now only an X data/HTML/JSON stage; it never runs AI, vector sync, market prices, or HC parsing. AI passes are separate pipeline stages.

Run from the code folder:

```bash
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-capture
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-rerender
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-reindex
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-raw-rebuild --replace-generated-json
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-repair-media-paths
PYTHONPATH=src python3 -m investment_tool.pipeline_orchestrator x-recover-media
```

The old X capture module remains as a compatibility wrapper:

```bash
PYTHONPATH=src python3 -m investment_tool.capture_threads
PYTHONPATH=src python3 -m investment_tool.capture_threads --rerender-only
```

Other product jobs can be run the same way:

```bash
PYTHONPATH=src python3 -m investment_tool.market_prices --from 2026-03-01
PYTHONPATH=src python3 -m investment_tool.hardcore_capture --no-analyze
PYTHONPATH=src python3 -m investment_tool.media_analysis --dry-run --limit 10
PYTHONPATH=src python3 -m investment_tool.manual_threads --bundle-name may31-screenshots --dry-run /path/to/screenshot.jpeg
PYTHONPATH=src python3 -m investment_tool.vector_store_sync --generate-only
PYTHONPATH=src python3 -m investment_tool.action_server
```

Manual X screenshots are imported as their own source bundles before AI analysis. Use `--analyze` only when you want GPT-5.5 to logically group overlapping screenshots, stitch scroll captures, reconstruct one or more visible X threads, and describe screenshots embedded inside the visible posts.

Before pushing code changes:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m py_compile src/investment_tool/*.py scripts/*.py tests/*.py
```

Storage details are documented in `docs/storage-layout.md`.

For a fresh Codex Desktop chat, use `docs/start-new-codex-chat.md`.
