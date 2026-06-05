# Storage Layout

This document describes the canonical runtime storage layout. Naming follows
the same rules as code: folder context carries meaning, child names stay short,
and source-specific names stay under `sources`.

The project is split into two clean places:

- Code lives in the repo checkout, referred to as `<repo>`
- Runtime data lives in `<data>`

`<data>` resolves from an explicit `--data-dir`, then
`INVESTMENT_TOOL_DATA_DIR`, then `INVESTMENT_TOOL_HOME/data`, then repo-local
`data/`. Relative paths are resolved from the portable project home.

Runtime data must not be committed to Git. `.env` must not be printed or
committed.

## Canonical Runtime Tree

```text
<data>/
├── sources/
│   ├── x/
│   │   ├── raw/
│   │   ├── records/
│   │   ├── media/
│   │   ├── ignored/
│   │   └── usage/
│   ├── articles/
│   │   ├── archive/
│   │   ├── records/
│   │   └── manifest.json
│   └── screenshots/
│       ├── inbox/
│       ├── bundles/
│       ├── media/
│       └── records/
├── context/
│   ├── prices/
│   │   ├── daily/
│   │   ├── hourly/
│   │   ├── intraday/
│   │   └── manifest.json
│   └── descriptions/
│       ├── x/
│       └── screenshots/
├── presentation/
│   ├── threads/
│   │   └── x/
│   └── indexes/
├── retrieval/
│   └── README.md
├── workflow/
│   ├── logs/
│   └── locks/
└── README.md
```

## Runtime Owners

| Location | Owner/stage | Purpose |
| --- | --- | --- |
| `sources/x/raw` | `x-capture`, `x-raw` | Saved X API responses by run |
| `sources/x/records` | `x-capture`, `x-raw` | Clean X thread source records |
| `sources/x/media` | `x-capture` | Downloaded X photo/image media |
| `sources/x/ignored` | `x-capture`, `x-raw`, `render` | Skipped thread records |
| `sources/x/usage` | `x-capture` | Local API usage estimates |
| `sources/articles/archive` | `articles` | Saved article archive input |
| `sources/articles/records` | `articles` | Normalized article source records |
| `sources/articles/manifest.json` | `articles` | Article ingest manifest |
| `sources/screenshots/inbox` | `screenshots` | Manual screenshot import inbox |
| `sources/screenshots/bundles` | `screenshots` | Imported screenshot bundle records |
| `sources/screenshots/media` | `screenshots` | Copied screenshot files by bundle |
| `context/prices/daily` | `prices` | Current implemented USD-normalized daily OHLCV bars |
| `context/prices/hourly` | `prices` | Planned recent hourly bars |
| `context/prices/intraday` | `prices` | Planned recent 15-minute bars |
| `context/descriptions/x` | `descriptions` | OCR/visual-description JSON for X media |
| `context/descriptions/screenshots` | `descriptions` | Planned OCR/visual-description JSON for manual screenshots |
| `presentation/threads/x` | `render` | Local readable X thread HTML pages |
| `presentation/indexes` | `render` | Browse indexes and browser-only owned ticker coloring |
| `retrieval` | Retrieval/search | Future vector/search memory output; currently empty aside from folder notes |
| `workflow/logs` | `workflow` | Plain workflow run logs, including `latest.log` |
| `workflow/locks` | `workflow` | Plain stale-timeout lock files |

## Folder Readmes

Small plain-English `README.md` files live in the main runtime folders. These
are intentionally AI-readable descriptions, not schemas. They explain what each
folder is for, what writes there, and which folder to inspect first when
debugging.

This keeps the data usable even if it is inspected without the codebase open.

## Temporary Folders

Some maintenance jobs may create short-lived staging folders such as
`sources/x/rebuild` or `sources/x/backups`. These are not part of the normal
steady-state tree and should be empty or absent after the maintenance job is
verified.

New code should read and write only the canonical layout above. Compatibility
wrappers may still exist in code, but they should resolve to canonical runtime
paths through `runtime/paths.py`.

## Repo Package Layout

Runtime storage mirrors the package hierarchy documented in
`docs/code-organization-spec.md`: `sources`, `context`, `presentation`,
`retrieval`, and `workflow` are both code concepts and storage concepts.
