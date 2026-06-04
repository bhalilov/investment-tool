# Article Source Spec

This spec records current saved article archive behavior before the package
refactor.

## Naming

Code should use `sources/articles`, not a source-specific code name. The current
configured archive may be AJ Investment Research Hardcore/Ghost, but that is
configuration, not package identity.

## Current Ingest

Article ingest:

- reads an existing manually downloaded archive;
- requires `article-index.json`;
- extracts text from saved HTML;
- collects HTML title and image alt text;
- skips scripts/styles/noscript/svg;
- applies configured cleanup regex patterns;
- writes normalized article JSON;
- writes Markdown evidence;
- can run a text-only AI analysis unless disabled.

## Boundaries

- Downloader/scraper support is placeholder only.
- OCR is not used for articles.
- Article context may be stale relative to later X posts and should be treated
  as supporting context, not current truth.

## Target Workflow

Article ingest is not part of scheduled `workflow update` v1. It is run through
explicit rebuild as stage `articles`.
