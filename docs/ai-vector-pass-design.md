# AI And Vector Pass Design

This document records the current AI/vector design decisions. It is separate
from the non-AI workflow plan because thread analysis and vector memory are
expensive and still need more review before implementation.

This document supersedes older Custom GPT/vector notes for implementation
decisions.

## Current Decision

Phase 1 thread AI does not use vector search initially.

Reason:

- the stripped pre-AI thread JSON is source material, not clean evidence;
- searching raw or weakly parsed thread data would add noise;
- current high-confidence JSON fields are not themselves useful semantic vector
  queries;
- vector search becomes valuable after Phase 1 has produced clean dated
  evidence.

## Phase 1 Inputs

Phase 1 should read direct, local source context:

- clean raw thread JSON;
- source profile and source-specific interpretation notes;
- thread reconstruction rules;
- media rules;
- thread-local media descriptions;
- direct market price lookups by ticker/date;
- clearly linked static context only when a thread references it by URL, title,
  or explicit known context.

Phase 1 should not:

- search the vector store before the AI call;
- upload raw stripped JSON as vector evidence;
- assign final priority, final signal, final actionability, or final portfolio
  state.

Phase 1 output should be clean evidence:

- source claims;
- answered questions;
- candidate timeline events;
- portfolio/action clues as vague evidence;
- media observations;
- tone/sarcasm/confusion markers;
- linked-context needs;
- ambiguities and second-pass reasons.

## Phase 1 Vector Behavior

The eventual post-Phase-1 behavior is:

```text
thread JSON + local context
  -> Phase 1 AI
  -> write JSON/Markdown evidence
  -> upsert clean Phase 1 evidence to vector
  -> move to next thread
```

Vector upsert details are not finalized in this slice.

## Phase 2 Inputs

Phase 2 starts only after the Phase 1 queue is complete enough for the intended
run.

Phase 2 may use vector search because the vector store should then contain
cleaner evidence:

- previous Phase 1 evidence;
- previous Phase 2 evidence when available;
- HC/static context;
- manual reconstructed screenshot evidence;
- human corrections;
- market context documents if approved later.

Phase 2 should resolve meaning only when context supports it, and preserve
uncertainty when it does not.

## Vector As Time-Sensitive Memory

The vector store must not be treated as one timeless memory blob.

Every evidence item inserted into vector must be strongly tied to time:

```text
what was said/done/claimed
who said it
about what ticker/company/topic
on what thread date
as of what evidence date
```

Historical evidence remains valuable, but it must not be confused with current
insight. For example:

```text
AJ took profit in PLTR in March 2026
```

is historical evidence, not a current PLTR recommendation.

Vector evidence should carry date metadata such as:

- source id;
- evidence type;
- thread id;
- thread date;
- event date when different;
- ticker/company;
- event type;
- validity such as `as_of_thread_date`;
- historical/current relevance when known.

## Evidence Shapes To Revisit

The vector design should likely use more than one evidence shape:

- thread-level evidence documents for readable source context;
- timeline event documents for precise dated memory;
- correction documents for human overrides;
- static context documents for HC/manual/market sources.

This is not finalized yet.

## Search Design To Revisit

Phase 2 and future production incremental runs need a controlled retrieval
profile. Search terms should come from meaningful text and questions, while
metadata fields act as filters.

Meaningful query sources:

- source-authored claims;
- answered parent questions;
- tickers and company aliases;
- linked context needs;
- media observations;
- pass-specific ambiguities.

Filters and safety rails:

- source id;
- source type;
- date window;
- ticker when high-confidence;
- exclude current thread id.

Metadata fields like `source_id`, `source_type`, and `thread_id` are not useful
search text by themselves. They are relevance controls.

## Open Decisions

Do not implement these until reviewed:

- exact vector evidence document format;
- whether timeline events are separate vector files;
- vector upsert/delete behavior for changed evidence;
- exact retrieval filters for Phase 2;
- whether static market context belongs in vector or only direct structured
  lookup;
- how human corrections trigger stale Phase 2/vector state.

