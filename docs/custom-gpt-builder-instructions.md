# Custom GPT Builder Instructions

> **SUPERSEDED REFERENCE**
>
> Superseded by `docs/ai-vector-pass-design.md`; do not use for implementation
> decisions.
>
> This document is older reference material for a future Custom GPT. Do not use
> it for implementation decisions about workflow orchestration, Phase 1 AI, or
> vector memory. Current decisions live in:
>
> - `docs/pipeline-orchestrator-plan.md`
> - `docs/ai-vector-pass-design.md`

## Goal

Create a Custom GPT that answers questions about AJ Investment Research content by calling this tool's backend through Actions.

The GPT should not rely on its own memory for factual answers about AJ posts, trades, thesis changes, contradictions, or timelines. It should call Actions first, then answer using returned evidence and source links.

## GPT Name

Suggested name:

```text
AJ Research Analyst
```

## GPT Description

Suggested description:

```text
Analyzes captured AJ Investment Research X threads, Ghost articles, screenshots/OCR, ticker memory, and trade signals using a private evidence backend.
```

## GPT Instructions

Paste this into the Custom GPT instructions field:

```text
You are an investment research assistant for analyzing AJ Investment Research content.

Always use Actions to retrieve evidence before answering factual questions about AJ posts, trades, thesis changes, contradictions, timelines, screenshots, Ghost articles, or ticker-specific history.

Do not rely on memory alone.

When answering:
- cite X post URLs when available
- cite captured thread HTML URLs when available
- cite Ghost links when relevant
- cite media or screenshot URLs when relevant
- distinguish AJ's actual statement from your interpretation
- flag uncertainty when evidence is incomplete
- prefer ticker memory plus evidence search over isolated thread summaries
- do not let random user replies dominate ticker classification
- do not treat a single thread as complete context for a ticker
- do not invent trades, positions, dates, prices, or claims that are not in the returned evidence

For broad questions such as "why did AJ change his mind about PLTR?", first retrieve ticker memory, then search evidence across X threads and Ghost articles. Build the answer from the timeline and cite sources.

For questions about current alerts or urgent signals, call the recent signals action.

For questions about one specific thread, call the get thread action.

For questions about screenshots, charts, or images, use returned OCR text and media links. Explain when the media itself is available only through a link.

If the Action results are incomplete, say what is missing and what additional evidence would be needed.
```

## Capabilities

Recommended settings:

- Web browsing: optional.
- Image generation: off.
- Code interpreter / data analysis: optional, not required for first version.
- Actions: on.
- Knowledge files: avoid uploading the full corpus manually. Use Actions and vector store backend instead.

## Why Not GPT Knowledge Files

Do not upload all AJ data directly into the GPT Knowledge section as the main architecture.

Reasons:

- The corpus will keep changing.
- Captured files need source links and metadata.
- The GPT needs to retrieve local/published artifacts through Actions.
- The backend can search vector store, local evidence, memory, and media links more reliably.

The GPT Knowledge area can contain a short operating guide if desired, but the real evidence should come from Actions.

## Action Server Requirement

The Custom GPT Action needs an HTTPS API endpoint when used outside local testing.

For first local implementation, the backend can run at:

```text
http://localhost:8787
```

For actual Custom GPT use, expose it through a private HTTPS endpoint:

```text
https://your-domain.com/aj-api
```

The backend must return source URLs, captured HTML URLs, media URLs, and evidence excerpts.

## Action Endpoints

The GPT should have these Actions:

```text
POST /aj/search
GET  /aj/thread/{thread_id}
GET  /aj/ticker/{ticker}/memory
POST /aj/timeline
POST /aj/recent-signals
```

## OpenAPI Schema Skeleton

Use this as the starting Action schema. Update the server URL once the backend is deployed.

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "AJ Investment Tool API",
    "version": "0.1.0"
  },
  "servers": [
    {
      "url": "https://your-domain.com/aj-api"
    }
  ],
  "paths": {
    "/aj/search": {
      "post": {
        "operationId": "searchEvidence",
        "summary": "Search AJ evidence across X threads, Ghost articles, OCR, and ticker memory.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "query": { "type": "string" },
                  "tickers": {
                    "type": "array",
                    "items": { "type": "string" }
                  },
                  "date_from": { "type": "string" },
                  "date_to": { "type": "string" },
                  "source_types": {
                    "type": "array",
                    "items": { "type": "string" }
                  },
                  "limit": { "type": "integer", "default": 10 }
                },
                "required": ["query"]
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Relevant evidence results with source links."
          }
        }
      }
    },
    "/aj/thread/{thread_id}": {
      "get": {
        "operationId": "getThread",
        "summary": "Return one compiled thread with posts, media, OCR, and source URLs.",
        "parameters": [
          {
            "name": "thread_id",
            "in": "path",
            "required": true,
            "schema": { "type": "string" }
          }
        ],
        "responses": {
          "200": {
            "description": "Compiled thread evidence."
          }
        }
      }
    },
    "/aj/ticker/{ticker}/memory": {
      "get": {
        "operationId": "getTickerMemory",
        "summary": "Return living memory for a ticker.",
        "parameters": [
          {
            "name": "ticker",
            "in": "path",
            "required": true,
            "schema": { "type": "string" }
          }
        ],
        "responses": {
          "200": {
            "description": "Ticker memory with sources."
          }
        }
      }
    },
    "/aj/timeline": {
      "post": {
        "operationId": "getTimeline",
        "summary": "Return a ticker timeline for a date range.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "ticker": { "type": "string" },
                  "date_from": { "type": "string" },
                  "date_to": { "type": "string" }
                },
                "required": ["ticker"]
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Ticker timeline events."
          }
        }
      }
    },
    "/aj/recent-signals": {
      "post": {
        "operationId": "getRecentSignals",
        "summary": "Return recent AJ action signals by priority and ownership filter.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "priority": {
                    "type": "array",
                    "items": { "type": "string" }
                  },
                  "date_from": { "type": "string" },
                  "owned_only": { "type": "boolean" }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Recent signal list."
          }
        }
      }
    }
  }
}
```

## Authentication

Use API key authentication for the first version.

The Custom GPT Action should send a secret API key to the backend. The backend should reject requests without the key.

Do not expose OpenAI API keys, X credentials, Pushover keys, or local file paths in GPT responses.

## Expected GPT Behavior Examples

Question:

```text
Why did AJ change his mind about PLTR?
```

Expected behavior:

1. Call `getTickerMemory` for PLTR.
2. Call `searchEvidence` for PLTR across recent X and Ghost evidence.
3. Answer with a dated timeline.
4. Cite actual X post URLs and captured thread URLs.
5. Separate facts from interpretation.

Question:

```text
Show me all recent P0/P1 signals for stocks I own.
```

Expected behavior:

1. Call `getRecentSignals`.
2. Return ticker, priority, summary, and links.

Question:

```text
What was in the screenshot from the MU thread?
```

Expected behavior:

1. Call `searchEvidence` or `getThread`.
2. Use OCR text and media URLs returned by the backend.
3. Cite the image link and X post link.

## Deployment Notes

For local-only testing, use `localhost`.

For real Custom GPT use from ChatGPT or iPad, deploy the backend behind HTTPS and publish readable artifacts behind HTTPS.

The Custom GPT does not need direct access to local files. It only needs the Action backend to return:

- relevant evidence text
- X URLs
- captured HTML URLs
- Ghost URLs
- media URLs
- OCR text
- confidence/uncertainty notes
