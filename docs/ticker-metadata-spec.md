# Ticker Metadata Spec

This spec records current non-AI ticker behavior before the package refactor.

## Source Of Truth

Ticker parsing uses `config/ticker_registry.json`.

Aliases map company names, display names, and listing variants to canonical
tickers. Unknown uppercase tokens are ignored unless registered.

## Non-AI Root Post Rule

The Python capture pass is intentionally conservative:

- If the root/source post contains exactly one recognized ticker, set it as
  `primary_ticker` and use it for the primary label.
- If the root/source post contains multiple recognized tickers, store them as
  `mentioned_only_tickers`.
- If no ticker is recognized, do not invent a primary ticker.

The Python pass does not decide context tickers, portfolio state, signal, final
priority, or final actionability.

## Mention Filtering

Example-only or risk-list tickers may be excluded from subject ticker extraction
when the sentence is clearly an example, broad black-swan risk, or similar
non-subject mention.

## Broad Indexes

Broad index tickers such as `SPY` and `QQQ` are recognized when explicit, but
company-name alias inference should not turn generic broad-market language into
those tickers unless configured.
