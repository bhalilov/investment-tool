# Articles Feed

This folder ingests saved article/archive material.

The current archive may contain AJ/Hardcore/Ghost content, but the code should
stay generic: treat it as a configured article feed.

## Rules

- Read saved archive files from `<data>/feeds/articles/archive`.
- Write normalized article records under `<data>/feeds/articles/records`.
- Use saved HTML text and image alt text.
- Do not OCR article images in this feed.
- Do not make the scheduled `workflow update` depend on article ingest in v1.
