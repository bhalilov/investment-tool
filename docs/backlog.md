# Backlog

This file captures decisions that survived the legacy cleanup audit. It is the
place to park real work, not old implementation surfaces.

## Legacy Extraction And Deletion

The old wrapper modules, direct console commands, vector sync, Custom GPT
action server, and storage migration command are deletion targets. Useful
behavior has been preserved here and in the focused specs before deleting the
old code.

| Legacy piece | Extracted value | Replacement path | Deletion condition |
| --- | --- | --- | --- |
| Root wrapper modules such as `capture_threads.py`, `market_prices.py`, `ticker_parser.py`, and `x_*` wrappers | Confirmed no unique logic; they only re-exported new modules | Import new package paths directly | Delete now |
| Old direct console scripts such as `investment-tool-x-capture`, `investment-tool-vector-sync`, and script launchers | Direct command names were transitional only | `investment-tool workflow ...` and explicit module tests | Delete now |
| Legacy X CLI flags | Raw rebuild, rerender, reindex, media-path repair, missing-media recovery are still useful maintenance jobs | Workflow stages and the internal `feeds/x/jobs.py` adapter | Keep behavior, delete old flag parser |
| Legacy vector sync | Useful mechanics: content hashing, manifest mapping, OpenAI file upload, vector-store attach, changed-file skip, old-file delete | Future retrieval v2 implementation, after AI/vector design is final | Delete old implementation now |
| Legacy vector evidence Markdown shape | Demonstrates why raw/thread-derived evidence was noisy | Mark rejected in retrieval notes | Do not reuse |
| Custom GPT action server | Useful endpoint ideas: search evidence, read thread, ticker timeline, recent signals | Future local UI/API backlog after evidence model exists | Delete old implementation now |
| Storage rename and `clean-old` migration command | Verified canonical layout and path rewrite behavior was useful during migration | `workflow check` plus canonical path resolver | Delete now after clean verification |

## Current Implementation Backlog

1. Promote X maintenance actions into explicit workflow rebuild/check commands:
   raw rebuild, rerender, reindex, media-path repair, and missing-media
   recovery.
2. Finish provider-native market price windows: daily from March 2026, hourly
   for the recent week, and 15-minute bars for the recent 48 hours.
3. Build article-review gating so article AI only runs against reviewed or
   reuploaded article archives.
4. Keep screenshot AI reconstruction in scheduled workflow when inbox files
   exist, and report clearly before/while paid reconstruction runs.
5. Build thread AI pass infrastructure after non-AI workflow is stable:
   Phase 1 has no vector retrieval; Phase 2 retrieval remains future work.
6. Design retrieval v2 around dated/as-of evidence, time-aware search, and
   replacement/deletion semantics.
7. Add future local API/UI only after the evidence model is no longer changing.

## Active Next Five

These are the currently approved near-term execution items from the workflow
stabilization pass.

| # | Item | Current status | Done when |
| --- | --- | --- | --- |
| 1 | Run a fresh small X smoke after `source_completeness` was added | Done: scratch run wrote 5 fresh records with explicit `source_completeness` values | Scratch capture/render produces fresh records whose JSON shows clear source completeness fields |
| 2 | Re-assess staged X raw rebuild delta | Done: staged rebuild has 765 active candidates vs 736 active, with 29 recoverable extras; defer promotion until missing media and source-completeness normalization are handled | We know why staged rebuild has more records than active and choose promote/defer/repair |
| 3 | Finish market price windows | Done in code and scratch-tested on 2 listings; full-universe production sync remains a deliberate provider-paced run | Provider-native daily/hourly/intraday outputs exist with USD normalization and tests |
| 4 | Run limited media description test | Done: 2-image `gpt-5.5` scratch test wrote neutral visual records; estimated cost `$0.060725` | A small paid test writes neutral image-description JSON with visible cost/reporting |
| 5 | Check screenshot workflow readiness | Checked: empty scheduled stage succeeds with no cost; non-empty import/reconstruction dry-run works; pending gap is converting reconstructed screenshot threads into canonical per-thread records/pages | Scheduled screenshot inbox behavior is verified or concrete missing pieces are listed |

## Newly Confirmed Follow-Ups

| Area | Follow-up | Reason |
| --- | --- | --- |
| X raw rebuild | Normalize raw-rebuilt records with `source_completeness` before active promotion | Staged raw rebuild recovers 29 extra records but currently has more media warnings and less precise completeness metadata than live capture |
| X raw rebuild | Recover/download missing still-image media before active promotion | Staged rebuild has 24 active media warnings vs 6 active warnings today |
| Market prices | Run full-universe production price sync deliberately | Code is ready and scratch-tested, but the provider can rate-limit and should be run as a visible longer job |
| Screenshot records | Convert reconstructed screenshot bundle threads into canonical per-thread records and presentation pages | Current screenshot AI reconstructs bundle JSON but does not yet create normal thread records comparable to X API records |
