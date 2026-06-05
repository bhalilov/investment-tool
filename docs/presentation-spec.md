# Presentation Spec

This spec records current HTML/index behavior before the package refactor.

Presentation files are derived output. JSON and raw API responses remain the
source of truth.

## Thread HTML

Thread pages show:

- navigation links to all/type/daily indexes;
- title;
- preview before AI or TLDR after AI;
- AI status when pending;
- primary ticker, context tickers, mentioned-only tickers;
- tags and type;
- post counts and feed-post counts;
- local JSON and X root links;
- evidence notes, ambiguities, and contradictions when available;
- posts in chronological order;
- downloaded images inline;
- image AI description blocks under downloaded images when matching
  `context/descriptions/x/<media_key>.json` files exist;
- pending image-description markers for downloaded images whose description JSON
  is still missing.

Owned ticker highlighting is browser-side and reads `indexes/current_owned.json`.
Owned status must not be written as static thread evidence.

## Index HTML

Indexes are interactive Tabulator pages. They include:

- all threads;
- by feed;
- by ticker;
- by type;
- by tag/category;
- by day.

Index dates are browser-rendered relative times from stored timestamps. They
must not be frozen as static "19h ago" text.

## Render Split

Feed capture does not own presentation output. The workflow `render` stage
regenerates pages and indexes from clean JSON plus available context files such
as image descriptions and browser-side owned ticker data.
