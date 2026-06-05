# Context

Context modules create supporting evidence used by later analysis.

Current context stages:

- `prices.py`: USD-normalized market price history.
- `descriptions.py`: neutral visual descriptions for downloaded images.

## Rules

- Context is dated evidence, not final interpretation.
- Price data should use `provider` terminology for market-data providers.
- Image descriptions should describe what is visible without deciding the
  thread's final investment meaning.
- Context output should remain tied to the original feed/media record.
