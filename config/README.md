# Config

Config files describe runtime behavior without changing Python code.

## Main Areas

| Folder/File | Purpose |
| --- | --- |
| `feeds/` | Feed profiles such as X accounts and article archives |
| `rules/` | Capture, reconstruction, and media handling rules |
| `ai/` | Model and pipeline registries |
| `market_price_universe.json` | Tracked companies/listings for price sync |
| `ticker_registry.json` | Company aliases and ticker normalization |
| `owned_positions.json` | Current owned ticker signal for presentation |

## Rules

- Do not store secrets here.
- Feed-specific notes belong in feed config, not in Python constants.
- Model and prompt choices should be configurable before paid AI runs.
- AI model profiles may set `provider`, `api_base`, and `api_key_env`.
  Store only the env var name here, never the key value.
- Use portable paths such as `<data>` and project-relative paths.
