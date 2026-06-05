# Code Organization Spec

This is the locked package and naming plan for the refactor.

## Naming Rules

- Folder context carries the feed name.
- Do not repeat prefixes inside a contextual folder.
- Use short nouns for helpers and clear verbs for jobs.
- Keep feed-specific code under `feeds`.
- Keep reusable records, rules, runtime helpers, analysis, retrieval, and
  presentation outside feed folders.

## Package Hierarchy

| Folder | Purpose |
| --- | --- |
| `cli/` | Command entrypoints only |
| `workflow/` | Workflow runner, stages, logs, locks, checks |
| `runtime/` | Env, config, paths, reporting |
| `feeds/x/` | X API capture, raw archive, rebuild, X thread assembly |
| `feeds/articles/` | Saved article/archive ingest |
| `feeds/screenshots/` | Screenshot inbox, bundles, reconstruction |
| `records/` | Canonical internal record shapes |
| `context/` | Supporting context such as prices and image descriptions |
| `analysis/` | Expensive AI passes and evidence generation |
| `retrieval/` | Vector/search memory and quarantined legacy sync |
| `presentation/` | HTML thread pages and indexes |
| `rules/` | Ticker parsing and feed-neutral filtering |

## Locked Module Names

| Current | New |
| --- | --- |
| `pipeline_orchestrator.py` | `workflow/run.py` plus `cli/main.py` |
| `capture_threads.py` | `cli/legacy_x_capture.py` |
| `x_client.py` | `feeds/x/api.py` |
| `x_capture_job.py` | `feeds/x/capture.py` |
| `x_raw_archive.py` | `feeds/x/raw.py` |
| `x_raw_rebuild.py` | `feeds/x/rebuild.py` |
| `x_thread_model.py` | `feeds/x/threads.py` and `feeds/x/media.py` |
| `x_capture_metadata.py` | `feeds/x/metadata.py` |
| `x_thread_store.py` | `feeds/x/store.py` |
| `hardcore_capture.py` | `feeds/articles/ingest.py` |
| `manual_threads.py` | `feeds/screenshots/bundles.py` and `feeds/screenshots/reconstruct.py` |
| `market_prices.py` | `context/prices.py` |
| `media_analysis.py` | `context/descriptions.py` |
| `index_render.py` | `presentation/indexes.py` |
| `x_thread_render.py` | `presentation/threads.py` |
| `vector_store_sync.py` | `retrieval/legacy.py` |
| `openai_api.py` | `analysis/openai.py` |
| `feed_config.py` | `runtime/config.py` |
| `runtime.py` | `runtime/env.py` |
| `reporting.py` | `runtime/reporting.py` |
| `ticker_parser.py` | `rules/tickers.py` |
| `thread_filtering.py` | `rules/filters.py` |

## Locked Stage Names

| Stage | Meaning |
| --- | --- |
| `x-capture` | Pull X data, save raw API, clean records, media |
| `screenshots` | Import/reconstruct screenshot threads |
| `prices` | Sync market prices |
| `descriptions` | OCR/describe images |
| `render` | Regenerate HTML and indexes |
| `articles` | Ingest saved article archives |
| `x-raw` | Rebuild X records from raw API |
| `check` / `doctor` | Read-only health checks |

## Refactor Rule

Move code first and preserve behavior first. Keep compatibility wrappers for old
module paths and old commands during the transition.

## Adapter Note

`feeds/x/jobs.py` is the intentional adapter between the coordinate-only
workflow runner and the X-specific stage commands. It owns legacy X CLI modes
such as rerender, raw rebuild, media-path repair, and missing-media recovery so
`workflow/run.py` does not contain X implementation details.
