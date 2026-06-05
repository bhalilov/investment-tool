# Rules

Rules modules contain feed-neutral parsing and filtering.

Current rules:

- `tickers.py`: conservative ticker/company extraction.
- `filters.py`: thread relevance and feed-author filtering helpers.

## Rules

- Keep these modules reusable across feeds.
- Do not import X API, article, screenshot, or presentation code here.
- Prefer conservative metadata. High-level meaning belongs in later AI passes.
