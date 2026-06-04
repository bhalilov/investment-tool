# Run Reporting Spec

This spec records current reporting behavior and the locked workflow target.

## Current Stdout Reporting

Current jobs use a shared reporter that emits:

- `START`
- `CHECKPOINT`
- `DONE`
- `FAILED`

Each line includes:

- a random bracketed drink-making word;
- job name;
- elapsed time;
- job-specific fields;
- optional processed/total/ETA;
- token and estimated-cost fields when available.

The random words are stdout-only decoration. They must not enter prompts, JSON
records, Markdown evidence, vector uploads, manifests, or AI context.

## Target Workflow Logs

Workflow v1 must also write plain AI-readable `.log` files under runtime
`pipeline/logs`.

Required files:

- timestamped run log;
- `latest.log`.

Logs should include:

- run id;
- command;
- git commit when available;
- start/end timestamps;
- mode;
- per-stage status;
- counts and notes;
- final status.

Locks live under runtime `pipeline/locks` as plain stale-timeout lock files.
