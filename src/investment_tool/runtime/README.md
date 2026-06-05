# Runtime

Runtime modules provide shared infrastructure that every stage can use.

This folder owns:

- environment loading;
- portable path resolution;
- config loading;
- status reporting;
- token/cost estimate helpers.

## Key Files

| File | Purpose |
| --- | --- |
| `env.py` | Load `.env` without printing secrets |
| `paths.py` | Resolve `<data>`, `<repo>`, and canonical storage folders |
| `config.py` | Load feed profiles, rules, model registries, and prompts |
| `reporting.py` | Shared job status, checkpoints, final reports |

## Rules

- Keep this layer generic.
- Do not import feed-specific modules from runtime helpers.
- Use `<data>` and `<repo>` tokens for portable path strings.
