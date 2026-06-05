# Deleted Legacy Retrieval Note

The old vector sync and Custom GPT action server code have been removed from
the active package. This note preserves the useful implementation ideas without
making the old behavior part of the current architecture.

## Rejected Old Behavior

The deleted sync generated Markdown evidence directly from captured X thread
JSON and uploaded that to an OpenAI vector store. That evidence shape is
rejected for the current design because pre-AI thread JSON is feed material, not
clean analysis evidence.

Do not rebuild the old raw/thread-derived Markdown upload path.

## Mechanics Worth Reusing Later

Future retrieval v2 may reuse these mechanics:

- content hashing before upload;
- manifest entries keyed by evidence document identity;
- changed-file skip behavior;
- OpenAI file upload followed by vector-store attachment;
- vector-store file removal and file deletion when replacing old evidence;
- compact metadata attributes such as feed, ticker, date, thread id, and media
  presence.

## API Ideas Worth Reconsidering Later

The deleted local action server also had useful product ideas:

- search evidence;
- read one reconstructed thread;
- return ticker memory;
- return a dated ticker timeline;
- return recent signals.

These are backlog ideas only. They should not be rebuilt until the evidence
model and AI/vector design are finalized.
