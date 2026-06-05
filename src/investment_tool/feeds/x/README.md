# X Feed

This folder owns X-specific capture and reconstruction.

## Main Files

| File | Purpose |
| --- | --- |
| `api.py` | X API request helpers |
| `capture.py` | Live capture stage and X maintenance helpers |
| `raw.py` | Read saved raw API responses |
| `rebuild.py` | Rebuild clean records from raw API |
| `threads.py` | Thread/media ownership helpers |
| `metadata.py` | Safe non-AI metadata: titles, tickers, labels, tags |
| `store.py` | Cached record/render lifecycle helpers |
| `jobs.py` | Adapter between workflow and X-specific commands |
| `context.py` | Loaded feed profile plus rules for this X account |

## Rules

- Capture writes raw API, clean records, and still-image media.
- Videos and animated GIFs become placeholders/tags.
- Python ticker parsing is intentionally conservative.
- AI analysis and vector upload do not belong here.
- Config decides feed account, reconstruction rules, and media rules.
