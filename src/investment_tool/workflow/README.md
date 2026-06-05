# Workflow

Workflow coordinates stages. It does not own feed-specific implementation.

The workflow layer is responsible for:

- parsing workflow commands;
- acquiring and releasing lock files;
- deciding stage order;
- calling stage modules with shared options;
- writing readable logs and final status;
- running read-only health checks;
- maintaining runtime storage names.

## Current Public Commands

```bash
investment-tool workflow update
investment-tool workflow sync
investment-tool workflow rebuild --stage render
investment-tool workflow rebuild --stage prices
investment-tool workflow check
```

`update`/`sync` are the normal frequent production cycle. Market prices are not
in that cycle; run `prices` explicitly through rebuild or a separate scheduler.

## Boundaries

- `workflow/run.py` should not know X API details.
- Stage implementation belongs in `feeds`, `context`, `presentation`,
  `analysis`, or `retrieval`.
