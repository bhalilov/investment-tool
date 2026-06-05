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
| `retrieval/` | Future vector/search memory |
| `presentation/` | HTML thread pages and indexes |
| `rules/` | Ticker parsing and feed-neutral filtering |

## Current Module Names

| Area | Modules |
| --- | --- |
| CLI | `cli/main.py` |
| Workflow | `workflow/run.py` |
| Runtime | `runtime/env.py`, `runtime/config.py`, `runtime/paths.py`, `runtime/reporting.py` |
| X feed | `feeds/x/api.py`, `feeds/x/capture.py`, `feeds/x/context.py`, `feeds/x/jobs.py`, `feeds/x/media.py`, `feeds/x/metadata.py`, `feeds/x/raw.py`, `feeds/x/rebuild.py`, `feeds/x/store.py`, `feeds/x/threads.py` |
| Article feed | `feeds/articles/ingest.py` |
| Screenshot feed | `feeds/screenshots/bundles.py`, `feeds/screenshots/reconstruct.py` |
| Context | `context/prices.py`, `context/descriptions.py` |
| Analysis | `analysis/openai.py` |
| Presentation | `presentation/html.py`, `presentation/indexes.py`, `presentation/threads.py` |
| Rules | `rules/tickers.py`, `rules/filters.py` |
| Retrieval | Empty package reserved for future retrieval v2 |

Deleted wrapper names and their extracted value are tracked in
`docs/backlog.md`.

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

Compatibility wrappers and old direct commands were temporary. New code imports
the package path that owns the behavior.

## Adapter Note

`feeds/x/jobs.py` is the intentional adapter between the coordinate-only
workflow runner and the X-specific stage commands. It owns X maintenance
actions such as rerender, raw rebuild, media-path repair, and missing-media
recovery so `workflow/run.py` does not contain X implementation details.
