# Legacy Retrieval Note

This note quarantines the existing vector sync code before the package refactor.

## Status

Existing vector sync can generate Markdown evidence from captured X thread JSON
and upload it to an OpenAI vector store. This is legacy utility code, not the
current AI/vector architecture.

## Why It Is Legacy

The current AI/vector design says:

- Phase 1 thread AI does not use vector search before the AI call;
- raw stripped JSON must not be uploaded as vector evidence;
- clean dated evidence should be produced before vector upsert;
- exact vector document shapes, search filters, and update/delete behavior are
  still undecided.

## Refactor Rule

Move existing vector sync to `retrieval/legacy.py` and keep any direct command
as a compatibility wrapper. Do not wire it into `workflow update`.

## Future Work

A future retrieval module should be designed from `docs/ai-vector-pass-design.md`
after the AI pass design is finalized.
