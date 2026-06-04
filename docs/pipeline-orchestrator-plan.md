# Workflow Orchestrator Plan

This is the current source-of-truth design for the non-thread-AI workflow
orchestrator. It supersedes older notes that refer to `pipeline run-due` or
the old `pipeline_orchestrator x-capture` command as the production interface.

## Goal

Build a top-down workflow system that can run scheduled incremental updates,
manual historical rebuilds, and read-only health checks without mixing source
capture, presentation rendering, AI passes, and vector-store decisions in one
large script.

The orchestrator coordinates work. Stage modules do the work.

## Public Commands

The public command group is `workflow`.

```bash
investment-tool workflow update
investment-tool workflow sync
investment-tool workflow refresh

investment-tool workflow rebuild --stage market-prices
investment-tool workflow rebuild --stage x-from-raw --stage render-indexes
investment-tool workflow rebuild --all

investment-tool workflow check
investment-tool workflow doctor
```

Aliases:

- `update`, `sync`, and `refresh` all mean the normal scheduled incremental run.
- `check` and `doctor` both mean read-only inspection.
- `rebuild` is manual historical or missing-data work.

Bare `workflow rebuild` must fail with a clear message telling the user to pass
one or more `--stage` values or explicit `--all`.

## Top-Level Control

An external scheduler, such as launchd or cron, wakes the tool. The tool does
not run as an internal daemon in v1.

The top-level flow is:

```text
external scheduler/manual command
  -> investment-tool workflow update
  -> orchestrator acquires lock
  -> orchestrator plans stages
  -> orchestrator runs stages in approved order
  -> orchestrator writes readable run log
  -> orchestrator releases lock
```

The orchestrator must stay coordinate-only:

- load config;
- acquire and release locks;
- choose stages;
- pass common options;
- collect stage results;
- write logs;
- return final status.

It must not contain source-specific X, HC, market-price, media, AI, or vector
implementation details.

## Stage Types

Every stage has one of three operating shapes.

### Batch Stage

Batch stages process a source or folder as a group.

Contract:

```text
scan -> plan -> run -> log
```

Examples:

- `x-capture`
- `market-prices`
- `media-description`
- `manual-import`
- `hc-ingest`
- `render-indexes`

### Cycle Stage

Cycle stages process one item at a time. The contract is generic in this plan;
thread AI/vector details are intentionally postponed.

Contract:

```text
scan -> build queue -> for each item: prepare -> run -> write -> post-step -> log
```

Future examples:

- `thread-pass1`
- `thread-pass2`

### Maintenance Stage

Maintenance stages inspect, rebuild, or repair local state. Normal scheduled
updates must not silently repair or rebuild data. Repairs and rebuilds require
explicit mode.

Examples:

- `check`
- `doctor`
- `x-from-raw`
- media path repair
- missing media recovery

## State And Logs

Use AI-readable plain logs, not SQLite and not rigid JSON stage-state files.

Data files remain the source of truth. The workflow decides what is due by
scanning data files and recent logs.

Runtime workflow files live outside the repo:

```text
/Users/burhanhalilov/investment-tool-data/pipeline/
  logs/
    20260604_153000__workflow-update.log
    latest.log
  locks/
    workflow-update.lock
```

Run logs should be plain text with stable headings, for example:

```text
# Investment Tool Workflow Run

RUN
id: 20260604_153000
command: workflow update
git_commit: abc123
started_at: 2026-06-04T15:30:00-04:00
mode: incremental

STAGE x-capture
status: success
items_seen: 20
items_written: 3
api_calls: 12
notes:
- downloaded 4 new photos
- skipped 17 cached threads

DONE
status: success
finished_at: 2026-06-04T15:38:00-04:00
```

Locking uses a plain readable lock file with a stale timeout so scheduled runs
do not overlap and crashed runs can be recovered.

## Workflow Update V1

`workflow update`, `workflow sync`, and `workflow refresh` run the same normal
incremental workflow.

Supported options:

- `--stage <id>`: run only selected stages; repeatable.
- `--skip <id>`: skip selected stages; repeatable.
- `--dry-run`: plan and report without API calls or data writes.
- `--force`: run selected stages even when scans suggest they are fresh.
- `--max-runtime-minutes N`: stop starting new stages after this window.

V1 scheduled update stage order:

```text
1. x-capture
2. manual-import
3. market-prices
4. media-description
5. render-indexes
```

Failure policy:

- Continue safe independent stages after a failure.
- Skip dependent stages when their inputs are unreliable.
- Return failed final status if any required stage failed.
- Record clear failure notes in the run log.

## Stage Responsibilities

### x-capture

Captures X source data only.

Writes:

- raw API responses;
- clean thread JSON;
- local photo media.

Does not:

- run thread AI;
- sync vector store;
- fetch market prices;
- parse HC;
- render HTML/indexes after the render split.

### manual-import

Uses a manual screenshot inbox in the runtime data folder. The inbox may be flat.

File timestamps are weak hints only. Manual screenshots are often iPad/X
screenshots with visible clocks and overlapping scroll regions. V1 scheduled
manual import should use AI for grouping, stitching, and reconstruction.

### market-prices

Extends current daily-only behavior.

Backfill/rebuild targets:

- daily OHLCV from March 1, 2026 to now;
- hourly bars for the last 7 days;
- 15-minute bars for the last 48 hours.

Incremental update:

- refresh currently due windows;
- prefer provider bars at the target granularity;
- do not derive daily/hourly bars from 15-minute bars;
- keep USD-normalized prices while preserving original currency and FX data.

### media-description

Runs image description/OCR preparation for new or changed downloaded photos.

This stage may call OpenAI in `workflow update`, but it is not the thread Phase
1 reasoning pass. Videos and animated GIFs remain placeholders only.

### render-indexes

Generates thread HTML and index pages from clean JSON. Rendering is split from
capture so source capture and presentation are not mixed.

### hc-ingest

HC/Ghost article ingest is not part of scheduled `workflow update` v1. It is an
explicit rebuild/manual stage:

```bash
investment-tool workflow rebuild --stage hc-ingest
```

## Workflow Rebuild V1

`workflow rebuild` is for manual historical or missing-data work.

Valid v1 stages:

- `x-from-raw`
- `market-prices`
- `media-description`
- `manual-import`
- `hc-ingest`
- `render-indexes`

The command requires one or more `--stage` values, or explicit `--all`.

## Workflow Check / Doctor V1

`workflow check` and `workflow doctor` are read-only in v1.

They inspect core data health:

- invalid JSON;
- media path pollution;
- missing media descriptions;
- missing thread HTML/index pages;
- stale market price windows;
- stale or orphaned locks;
- workflow log problems.

Future AI diagnosis and fix commands are reserved for v2. V1 may display a
placeholder, but it must not mutate files.

## Out Of Scope For This Slice

Do not implement these as part of the non-AI workflow orchestrator slice:

- thread Phase 1 AI runner;
- thread Phase 2 AI runner;
- vector search before/inside thread AI;
- vector upsert for thread AI outputs;
- time-sensitive vector timeline memory implementation.

Those decisions live in `docs/ai-vector-pass-design.md`.

