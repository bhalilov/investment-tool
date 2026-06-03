# Storage Layout

The project is split into two clean places:

- Code lives in `/Users/burhanhalilov/code/investment-tool`
- Runtime data lives in `/Users/burhanhalilov/investment-tool-data`

```mermaid
flowchart LR
    Repo["Code repo<br/>/Users/burhanhalilov/code/investment-tool"]
    Data["Local data<br/>/Users/burhanhalilov/investment-tool-data"]
    Drive["Google Drive<br/>optional report copies only"]

    Repo -->|"runs capture scripts"| Data
    Data -->|"manual copy/export later"| Drive

    Repo --> Src["src/<br/>capture and analysis code"]
    Repo --> Config["config/<br/>ticker registry, owned positions"]
    Repo --> Env[".env<br/>private API credentials"]
    Repo --> Docs["docs/<br/>notes and layout"]

    Data --> XThreads["x_threads/"]
    XThreads --> Threads["threads/<br/>readable thread HTML"]
    XThreads --> Indexes["indexes/<br/>main index plus ticker/tag/type/date indexes"]
    XThreads --> Json["thread_json/<br/>structured thread data and AI metadata"]
    XThreads --> Media["media/<br/>downloaded screenshots/images"]
    XThreads --> Raw["raw_api/<br/>raw X responses by run"]
    XThreads --> Ignored["ignored/<br/>audit trail for skipped items"]
    XThreads --> Usage["usage/<br/>rough API/cost logs"]
```

## What Each Folder Means

| Location | Purpose | Keep in Git? |
| --- | --- | --- |
| `/Users/burhanhalilov/code/investment-tool/src` | The actual tool code | Yes |
| `/Users/burhanhalilov/code/investment-tool/config` | Local ticker/position config | Yes for non-secret config |
| `/Users/burhanhalilov/code/investment-tool/.env` | X, OpenAI, email, and other credentials | No |
| `/Users/burhanhalilov/investment-tool-data/x_threads/threads` | One readable HTML page per captured thread | No |
| `/Users/burhanhalilov/investment-tool-data/x_threads/indexes` | Browse pages: all threads, ticker pages, tags, type, daily | No |
| `/Users/burhanhalilov/investment-tool-data/x_threads/thread_json` | Stored thread records, AI output, fingerprints, source post data | No |
| `/Users/burhanhalilov/investment-tool-data/x_threads/media` | Downloaded X images/screenshots | No |
| `/Users/burhanhalilov/investment-tool-data/x_threads/raw_api` | Raw API evidence for each run | No |
| `/Users/burhanhalilov/investment-tool-data/x_threads/ignored` | Skipped/irrelevant items, kept for audit | No |
| `/Users/burhanhalilov/investment-tool-data/x_threads/usage` | Rough X/OpenAI usage and cost logs | No |

Google Drive should stay out of the live workflow. If reports need to be shared later, copy only finished report files there.
