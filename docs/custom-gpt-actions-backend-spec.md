# Custom GPT Actions Backend Spec

> **SUPERSEDED REFERENCE**
>
> Superseded by `docs/ai-vector-pass-design.md`; do not use for implementation
> decisions.
>
> This document is older reference material. Do not use it for implementation
> decisions about workflow orchestration, Phase 1 AI, or vector memory.
> Current decisions live in:
>
> - `docs/pipeline-orchestrator-plan.md`
> - `docs/ai-vector-pass-design.md`

## Goal

Build the backend that lets a Custom GPT answer questions about AJ Investment Research content using captured X threads, Ghost articles, screenshots/OCR, and living ticker memory.

The Custom GPT must use Actions to call this backend. The backend searches OpenAI vector stores and returns compact evidence packets with source links. The GPT writes the final answer using those returned sources.

## Core Rules

- Raw captured data stays local as the source of truth.
- Do not upload raw X API JSON as the main RAG material.
- Generate clean Markdown evidence documents from raw captures.
- Upload Markdown evidence documents and ticker memory documents to OpenAI vector store.
- Expose captured thread HTML, media, Ghost captures, and evidence docs through HTTP/HTTPS URLs so the GPT can cite them.
- The GPT cannot use `file:///Users/...` links. It needs web URLs returned by the backend.

## Local Data Layout

Use this local data root:

```text
~/investment-tool-data/
  x_threads/
    raw_json/
    threads/
    media/
    ocr/
    evidence/
  ghost/
    raw/
    evidence/
  memory/
    tickers/
    global_rules.md
    audit.jsonl
```

Use this repo:

```text
~/code/investment-tool/
```

## Evidence Documents

Every captured X thread should generate one Markdown evidence file.

Example:

```text
~/investment-tool-data/x_threads/evidence/20260601__PLTR__2061424788300853554.md
```

Required format:

```md
# PLTR - Bullish momentum and valuation

Source X URL: https://x.com/alojohhardcore/status/2061424788300853554
Captured HTML URL: http://localhost:8787/threads/20260601__PLTR__2061424788300853554.html
Captured Date: 2026-06-01
Source Type: x_thread
Thread ID: 2061424788300853554
Primary Ticker: PLTR
Tickers: PLTR
Noise: false
Has OCR: true
Has Media: true

## Thread Summary

Short summary of what AJ is saying.

## AJ Posts

### 2026-06-01 10:14 UTC
Post URL: https://x.com/alojohhardcore/status/...
Text:
...

### 2026-06-01 10:41 UTC
Post URL: https://x.com/alojohhardcore/status/...
Text:
...

## Questions AJ Answered

### Question
Author: @someuser
Post URL: https://x.com/...
Text:
...

### AJ Reply
Post URL: https://x.com/alojohhardcore/status/...
Text:
...

## Screenshots And OCR

### Media 1
Media URL: http://localhost:8787/media/...
Original X Media URL: ...
OCR Text:
...

## Linked Context

Previous X thread:
- https://x.com/alojohhardcore/status/...

Ghost article:
- https://aj-investment-research.ghost.io/...

## Analyst Notes

- Possible action signal:
- Contradictions:
- Changed thesis:
- Open questions:
```

## Ghost Evidence Documents

Every Ghost article should also become a Markdown evidence document.

Example:

```text
~/investment-tool-data/ghost/evidence/20260531__PLTR__article-title.md
```

Required format:

```md
# PLTR - Ghost Article Title

Ghost URL: https://aj-investment-research.ghost.io/...
Captured HTML URL: http://localhost:8787/ghost/...
Captured Date: 2026-05-31
Source Type: ghost_article
Primary Ticker: PLTR
Tickers: PLTR
Noise: false

## Article Summary

...

## Full Extracted Text

...

## AJ Claims / Thesis

...

## Trade Mentions

...

## Possible Conflicts With X Posts

...
```

## Living Memory

Maintain one living memory Markdown file per ticker or major topic.

Example:

```text
~/investment-tool-data/memory/tickers/PLTR.md
```

Required format:

```md
# PLTR Memory

Last Updated: 2026-06-02

## Current AJ Position / Thesis

...

## Timeline

### 2026-05-29
Source: https://x.com/...
AJ said:
Interpretation:

### 2026-06-01
Source: https://x.com/...
AJ said:
Interpretation:

## Known Trades / Trims / Exits

...

## Contradictions / Concern Areas

...

## Open Questions

...

## Source Evidence Files

- 20260601__PLTR__2061424788300853554.md
```

Do not create versioned memory Markdown files. Keep only the current memory file plus an audit log.

Audit log:

```text
~/investment-tool-data/memory/audit.jsonl
```

Each line:

```json
{
  "timestamp": "2026-06-02T12:00:00Z",
  "memory_file": "tickers/PLTR.md",
  "source_evidence": ["20260601__PLTR__2061424788300853554.md"],
  "change_summary": "Added AJ's June 1 PLTR bullish valuation comments."
}
```

## Vector Store Upload Policy

Upload only:

```text
x_threads/evidence/*.md
ghost/evidence/*.md
memory/tickers/*.md
memory/global_rules.md
```

Do not upload:

```text
raw_json/
media/
large raw API dumps
duplicate HTML unless specifically needed
```

Media should be linked from evidence docs, not embedded.

## Vector Store Metadata

When uploading each evidence file to the OpenAI vector store, attach metadata/attributes.

For X thread evidence:

```json
{
  "source_type": "x_thread",
  "thread_id": "2061424788300853554",
  "date": "2026-06-01",
  "primary_ticker": "PLTR",
  "tickers": "PLTR",
  "has_ocr": true,
  "has_media": true,
  "noise": false,
  "content_type": "evidence_thread"
}
```

For Ghost evidence:

```json
{
  "source_type": "ghost_article",
  "date": "2026-05-31",
  "primary_ticker": "PLTR",
  "tickers": "PLTR",
  "noise": false,
  "content_type": "ghost_article"
}
```

For memory files:

```json
{
  "source_type": "memory",
  "primary_ticker": "PLTR",
  "content_type": "ticker_memory",
  "date": "2026-06-02"
}
```

## Published Artifact URLs

For local testing, expose artifacts through a local HTTP server:

```text
http://localhost:8787/
```

For iPad or remote Custom GPT usage, expose the same artifacts through private HTTPS later:

```text
https://your-domain.com/aj/
```

Artifacts to expose:

```text
/threads/{thread_file}.html
/media/{media_file}
/ghost/{ghost_file}.html
/evidence/{evidence_file}.md
```

Evidence docs should include these URLs.

## Backend API

Build a small backend API for Custom GPT Actions.

### Search Evidence

```http
POST /aj/search
```

Request:

```json
{
  "query": "Why did AJ change his mind about PLTR?",
  "tickers": ["PLTR"],
  "date_from": "2026-05-29",
  "date_to": "2026-06-02",
  "source_types": ["x_thread", "ghost_article", "memory"],
  "limit": 10
}
```

Response:

```json
{
  "query": "Why did AJ change his mind about PLTR?",
  "results": [
    {
      "title": "PLTR - Bullish momentum and valuation",
      "source_type": "x_thread",
      "date": "2026-06-01",
      "primary_ticker": "PLTR",
      "summary": "...",
      "evidence_excerpt": "...",
      "x_url": "https://x.com/alojohhardcore/status/...",
      "captured_html_url": "http://localhost:8787/threads/...",
      "evidence_url": "http://localhost:8787/evidence/...",
      "media_urls": [
        "http://localhost:8787/media/..."
      ]
    }
  ]
}
```

### Get Thread

```http
GET /aj/thread/{thread_id}
```

Response:

```json
{
  "thread_id": "2061424788300853554",
  "title": "PLTR - Bullish momentum and valuation",
  "x_url": "https://x.com/alojohhardcore/status/...",
  "captured_html_url": "http://localhost:8787/threads/...",
  "evidence_markdown": "...",
  "posts": [
    {
      "author": "@alojohhardcore",
      "created_at": "2026-06-01T10:14:00Z",
      "text": "...",
      "x_url": "https://x.com/..."
    }
  ],
  "media": [
    {
      "type": "image",
      "url": "http://localhost:8787/media/...",
      "ocr_text": "..."
    }
  ]
}
```

### Get Ticker Memory

```http
GET /aj/ticker/{ticker}/memory
```

Response:

```json
{
  "ticker": "PLTR",
  "last_updated": "2026-06-02",
  "memory_markdown": "...",
  "sources": [
    {
      "title": "...",
      "x_url": "...",
      "captured_html_url": "..."
    }
  ]
}
```

### Get Timeline

```http
POST /aj/timeline
```

Request:

```json
{
  "ticker": "PLTR",
  "date_from": "2026-05-29",
  "date_to": "2026-06-02"
}
```

Response:

```json
{
  "ticker": "PLTR",
  "events": [
    {
      "date": "2026-05-29",
      "event_type": "thesis_update",
      "summary": "...",
      "source_url": "https://x.com/...",
      "captured_html_url": "http://localhost:8787/threads/..."
    }
  ]
}
```

### Get Recent Signals

```http
POST /aj/recent-signals
```

Request:

```json
{
  "priority": ["P0", "P1", "P2"],
  "date_from": "2026-06-01",
  "owned_only": true
}
```

Response:

```json
{
  "signals": [
    {
      "priority": "P0",
      "ticker": "MU",
      "summary": "...",
      "x_url": "https://x.com/...",
      "captured_html_url": "http://localhost:8787/threads/..."
    }
  ]
}
```

## Backend Behavior

For each user question, the backend should:

1. Identify likely ticker/topic.
2. Retrieve ticker memory first if ticker exists.
3. Search vector store for matching evidence documents.
4. Prefer AJ-authored posts, AJ replies, Ghost articles, and OCR from screenshots.
5. Return compact evidence packets with URLs.
6. Let the Custom GPT write the final human answer.

## Why This Design

The Custom GPT cannot directly access local files.

It can access:

- built-in GPT knowledge files
- public or private web URLs
- data returned by Actions

Therefore, local captured content must be made available through the backend as:

- searchable vector evidence
- readable HTTP/HTTPS links
- JSON responses from Action endpoints

Raw JSON remains local and immutable. Markdown evidence is uploaded and searchable. Memory files provide accumulated context. Actions connect the GPT to all of it.
