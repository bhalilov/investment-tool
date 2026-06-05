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
