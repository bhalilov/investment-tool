# Market Data Spec

This spec records current market data behavior and the locked target gaps.

## Current Behavior

Current price sync:

- reads `config/market_price_universe.json`;
- writes runtime `context/prices/daily`;
- uses Massive first when appropriate for US symbols;
- falls back to Yahoo chart data;
- converts non-USD prices to USD;
- preserves original currency and original price fields;
- writes a manifest with companies, listings, rows, and errors.

Current FX mappings:

- EUR via `EURUSD=X`;
- HKD via `USDHKD=X` inverse;
- KRW via `USDKRW=X` inverse.

## Target Behavior

The locked workflow needs:

- daily OHLCV from March 1, 2026 to now;
- hourly bars for the last 7 days;
- 15-minute bars for the last 48 hours;
- incremental refresh of currently due windows when the `prices` stage is run
  explicitly.

Market prices are not part of the normal 15-minute `workflow update` /
`workflow sync` production cycle. Run them with `workflow rebuild --stage
prices` or a separate scheduler cadence.

Do not derive daily/hourly bars by aggregating 15-minute bars unless explicitly
approved later. Prefer provider bars at the requested granularity.

## Naming

The stage name is `prices`; code belongs under `context/prices.py`.
