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
investment-tool workflow rebuild --stage render
investment-tool workflow check
investment-tool storage rename --verify-only
```

## Boundaries

- `workflow/run.py` should not know X API details.
- `workflow/storage.py` only renames/verifies local runtime folders and path
  strings; it does not run capture, AI, or market-data jobs.
- Stage implementation belongs in `feeds`, `context`, `presentation`,
  `analysis`, or `retrieval`.
