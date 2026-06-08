# `investment_tool` Package

This package contains the production code for the local investment research
pipeline.

Use the root `README.md` for project-wide purpose and rules. Use this folder as
the implementation map.

## Package Map

| Folder | Belongs here | Does not belong here |
| --- | --- | --- |
| `cli/` | Public command entrypoints | Business logic |
| `workflow/` | Stage orchestration, locks, logs, storage maintenance | Feed-specific capture code |
| `runtime/` | Env, config, portable paths, reporting | Stage behavior |
| `feeds/` | Feed-specific capture/ingest modules | Shared parsing rules |
| `context/` | Supporting context such as prices and image descriptions | Feed capture |
| `analysis/` | Shared AI/OpenAI helpers and future expensive AI passes | Capture side effects |
| `retrieval/` | Future retrieval memory | New capture logic |
| `interfaces/` | External API surfaces such as MCP and Custom GPT | Core pipeline behavior |
| `presentation/` | HTML pages and indexes | Record reconstruction |
| `rules/` | Feed-neutral ticker parsing and filtering | Feed-specific API code |
| `records/` | Future explicit record model definitions | Ad hoc job code |

## Rules

- Put reusable production logic here, not in `scripts/`.
- Keep capture, context, presentation, analysis, and retrieval separate.
- Use config files for feed accounts, prompts, models, and capture rules.
- Prefer short module names inside contextual folders.
- Do not add root-level compatibility wrappers for old module names.
