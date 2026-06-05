# Retrieval

Retrieval is for vector/search memory.

Current code is legacy/quarantined because the AI/vector design is not final.

| File | Status |
| --- | --- |
| `legacy.py` | Old evidence generation/vector sync behavior |
| `server.py` | Local evidence API, useful but not the final vector design |

## Rules

- Do not add new capture behavior here.
- Do not treat legacy evidence files as final AI analysis.
- Future retrieval should be time-aware and use dated/as-of evidence.
- Vector push/search decisions must follow `docs/ai-vector-pass-design.md`.
