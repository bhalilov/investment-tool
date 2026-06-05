#!/usr/bin/env python3
"""Download market prices for tracked companies."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from investment_tool.runtime.env import load_env
from investment_tool.runtime.paths import portable_path, storage_paths
from investment_tool.runtime.reporting import report_event, start_reporter


DEFAULT_CONFIG = Path("config/market_price_universe.json")
MASSIVE_BASE = "https://api.massive.com"
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
USD_CURRENCIES = {"USD", None, ""}
FX_SYMBOLS = {
    "EUR": ("EURUSD=X", "direct"),
    "HKD": ("USDHKD=X", "inverse"),
    "KRW": ("USDKRW=X", "inverse"),
}
WINDOWS = {
    "daily": {
        "massive_multiplier": 1,
        "massive_timespan": "day",
        "yahoo_interval": "1d",
        "storage_attr": "prices_daily",
        "lookback_days": None,
    },
    "hourly": {
        "massive_multiplier": 1,
        "massive_timespan": "hour",
        "yahoo_interval": "1h",
        "storage_attr": "prices_hourly",
        "lookback_days": 7,
    },
    "intraday": {
        "massive_multiplier": 15,
        "massive_timespan": "minute",
        "yahoo_interval": "15m",
        "storage_attr": "prices_intraday",
        "lookback_days": 2,
    },
}


def safe_symbol(symbol: str) -> str:
    return symbol.replace("/", "_").replace(".", "_").upper()


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def iso_from_ms(value: int) -> str:
    return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date().isoformat()


def iso_from_seconds(value: int) -> str:
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).date().isoformat()


def iso_datetime_from_ms(value: int) -> str:
    return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).isoformat()


def iso_datetime_from_seconds(value: int) -> str:
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()


def request_json(url: str, headers: dict[str, str] | None = None, retries: int = 3) -> dict[str, Any]:
    headers = headers or {}
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < retries - 1:
                wait = 65
                report_event(
                    "WAITING",
                    "prices",
                    reason="provider_rate_limit",
                    wait_seconds=wait,
                    url=url.split("?")[0],
                    attempt=attempt + 1,
                    retries=retries,
                )
                time.sleep(wait)
                continue
            report_event(
                "ERROR",
                "prices",
                reason="request_failed",
                status=exc.code,
                url=url.split("?")[0],
                error=body[:500],
            )
            raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc
    raise RuntimeError(f"request failed after {retries} retries: {url.split('?')[0]}")


def massive_bars(
    symbol: str,
    start: str,
    end: str,
    api_key: str,
    multiplier: int,
    timespan: str,
    window: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": api_key,
        }
    )
    url = (
        f"{MASSIVE_BASE}/v2/aggs/ticker/{urllib.parse.quote(symbol, safe='')}"
        f"/range/{multiplier}/{timespan}/{start}/{end}?{params}"
    )
    data = request_json(url)
    rows = []
    for item in data.get("results") or []:
        timestamp = iso_datetime_from_ms(item["t"])
        rows.append(
            {
                "date": timestamp[:10],
                **({} if window == "daily" else {"timestamp": timestamp}),
                "open": item.get("o"),
                "high": item.get("h"),
                "low": item.get("l"),
                "close": item.get("c"),
                "adjusted_close": item.get("c"),
                "volume": item.get("v"),
                "transactions": item.get("n"),
                "vwap": item.get("vw"),
            }
        )
    meta = {
        "provider": "massive",
        "provider_symbol": data.get("ticker") or symbol,
        "status": data.get("status"),
        "results_count": data.get("resultsCount") or len(rows),
        "adjusted": True,
        "window": window,
        "provider_interval": f"{multiplier}/{timespan}",
    }
    return rows, meta


def massive_daily(symbol: str, start: str, end: str, api_key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return massive_bars(symbol, start, end, api_key, 1, "day", "daily")


def yahoo_bars(symbol: str, start: str, end: str, interval: str, window: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start_dt = dt.datetime.combine(parse_date(start), dt.time.min, tzinfo=dt.timezone.utc)
    # Yahoo period2 is exclusive. Add one day so the requested end date is included.
    end_dt = dt.datetime.combine(parse_date(end) + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
    params = urllib.parse.urlencode(
        {
            "period1": int(start_dt.timestamp()),
            "period2": int(end_dt.timestamp()),
            "interval": interval,
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = f"{YAHOO_BASE}/{urllib.parse.quote(symbol, safe='')}?{params}"
    data = request_json(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    chart = data.get("chart") or {}
    result = (chart.get("result") or [None])[0]
    if not result:
        error = chart.get("error")
        raise RuntimeError(f"Yahoo returned no result for {symbol}: {error}")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    rows = []
    for i, ts in enumerate(timestamps):
        close = (quote.get("close") or [None] * len(timestamps))[i]
        if close is None:
            continue
        timestamp = iso_datetime_from_seconds(ts)
        rows.append(
            {
                "date": timestamp[:10],
                **({} if window == "daily" else {"timestamp": timestamp}),
                "open": (quote.get("open") or [None] * len(timestamps))[i],
                "high": (quote.get("high") or [None] * len(timestamps))[i],
                "low": (quote.get("low") or [None] * len(timestamps))[i],
                "close": close,
                "adjusted_close": adj[i] if i < len(adj) else close,
                "volume": (quote.get("volume") or [None] * len(timestamps))[i],
            }
        )
    meta_src = result.get("meta") or {}
    meta = {
        "provider": "yahoo_chart",
        "provider_symbol": symbol,
        "currency": meta_src.get("currency"),
        "exchange": meta_src.get("exchangeName"),
        "full_exchange": meta_src.get("fullExchangeName"),
        "instrument_type": meta_src.get("instrumentType"),
        "results_count": len(rows),
        "adjusted": True,
        "window": window,
        "provider_interval": interval,
    }
    return rows, meta


def yahoo_daily(symbol: str, start: str, end: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return yahoo_bars(symbol, start, end, "1d", "daily")


def fx_daily(currency: str, start: str, end: str) -> tuple[dict[str, float], dict[str, Any]]:
    fx = FX_SYMBOLS.get(currency)
    if not fx:
        raise RuntimeError(f"No FX mapping configured for {currency}")
    symbol, direction = fx
    rows, meta = yahoo_daily(symbol, start, end)
    rates: dict[str, float] = {}
    for row in rows:
        close = row.get("close")
        if close is None:
            continue
        value = float(close)
        rates[row["date"]] = value if direction == "direct" else 1 / value
    return rates, {
        "fx_provider": meta.get("provider"),
        "fx_provider_symbol": symbol,
        "fx_direction": direction,
        "fx_currency": currency,
        "fx_rows": len(rates),
    }


def convert_rows_to_usd(
    rows: list[dict[str, Any]],
    currency: str | None,
    fx_cache: dict[str, tuple[dict[str, float], dict[str, Any]]],
    start: str,
    end: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if currency in USD_CURRENCIES:
        converted = []
        for row in rows:
            copied = dict(row)
            copied["date"] = row_bar_date(copied)
            copied["currency"] = "USD"
            copied["fx_rate_to_usd"] = 1.0
            copied["original_currency"] = "USD"
            converted.append(copied)
        return converted, {"currency": "USD", "prices_converted_to_usd": False}

    if currency not in fx_cache:
        fx_cache[currency] = fx_daily(str(currency), start, end)
    rates, fx_meta = fx_cache[currency]
    rate_dates = sorted(rates)

    converted = []
    last_rate: float | None = None
    missing_dates: list[str] = []
    price_fields = ("open", "high", "low", "close", "adjusted_close")
    for row in rows:
        row_date = row_bar_date(row)
        rate = rates.get(row_date)
        if rate is None:
            missing_dates.append(row_date)
            rate = last_rate or previous_fx_rate(rates, rate_dates, row_date)
        if rate is None:
            raise RuntimeError(f"Missing FX rate for {currency} on {row_date}")
        last_rate = rate
        copied = dict(row)
        copied["date"] = row_date
        copied["original_currency"] = currency
        for field in price_fields:
            value = copied.get(field)
            copied[f"original_{field}"] = value
            copied[field] = None if value is None else float(value) * rate
        copied["currency"] = "USD"
        copied["fx_rate_to_usd"] = rate
        converted.append(copied)

    return converted, {
        "currency": "USD",
        "original_currency": currency,
        "prices_converted_to_usd": True,
        "fx_missing_dates_filled": missing_dates,
        **fx_meta,
    }


def previous_fx_rate(rates: dict[str, float], rate_dates: list[str], row_date: str) -> float | None:
    for candidate in reversed(rate_dates):
        if candidate <= row_date:
            return rates[candidate]
    return None


def row_bar_date(row: dict[str, Any]) -> str:
    value = str(row.get("date") or "")
    if value:
        return value[:10]
    timestamp = str(row.get("timestamp") or "")
    if timestamp:
        return timestamp[:10]
    raise RuntimeError("Price row missing date/timestamp")


def should_try_massive(symbol: str, market: str) -> bool:
    if "." in symbol:
        return False
    if "US" in market.upper():
        return True
    return market.upper() == "US"


def fetch_listing(
    symbol: str,
    market: str,
    start: str,
    end: str,
    api_key: str,
    window: str = "daily",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    errors: list[str] = []
    window_config = WINDOWS[window]
    if api_key and should_try_massive(symbol, market):
        try:
            rows, meta = massive_bars(
                symbol,
                start,
                end,
                api_key,
                int(window_config["massive_multiplier"]),
                str(window_config["massive_timespan"]),
                window,
            )
            if rows:
                return rows, meta
            errors.append("massive returned no bars")
        except Exception as exc:
            errors.append(f"massive: {exc}")
    try:
        rows, meta = yahoo_bars(symbol, start, end, str(window_config["yahoo_interval"]), window)
        if rows:
            if errors:
                meta["fallback_from"] = errors
            return rows, meta
        errors.append("yahoo returned no bars")
    except Exception as exc:
        errors.append(f"yahoo: {exc}")
    raise RuntimeError("; ".join(errors) or "no provider attempted")


def selected_windows(values: list[str]) -> list[str]:
    if not values:
        return list(WINDOWS)
    return list(dict.fromkeys(values))


def window_start_date(window: str, configured_start: str, end: str) -> str:
    lookback = WINDOWS[window]["lookback_days"]
    if lookback is None:
        return configured_start
    end_date = parse_date(end)
    return (end_date - dt.timedelta(days=int(lookback))).isoformat()


def iter_listings(companies: list[dict[str, Any]], limit: int = 0) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs = [
        (company, listing)
        for company in companies
        for listing in company.get("listings") or []
    ]
    return pairs[:limit] if limit else pairs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync OHLCV prices for tracked companies.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--from", dest="start", default="")
    parser.add_argument("--to", dest="end", default=dt.date.today().isoformat())
    parser.add_argument("--window", action="append", choices=tuple(WINDOWS), default=[], help="Sync only this window; repeatable.")
    parser.add_argument("--limit-listings", type=int, default=0, help="Limit listing count for smoke tests.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--sleep", type=float, default=13.0, help="Seconds between Massive requests.")
    args = parser.parse_args(argv)

    load_env(Path(args.env))
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    storage = storage_paths(args.data_dir or None)
    data_dir = storage.root
    start = args.start or config.get("start_date") or "2026-03-01"
    end = args.end
    companies = config.get("companies") or []
    windows = selected_windows(args.window)
    listing_pairs = iter_listings(companies, args.limit_listings)
    total_units = len(listing_pairs) * len(windows)
    reporter = start_reporter(
        "prices",
        total=total_units,
        every_items=3,
        every_seconds=30,
        mode="sync",
        config=portable_path(config_path.resolve()),
        data_dir=portable_path(data_dir),
        start=start,
        end=end,
        windows=",".join(windows),
        companies=len(companies),
        listings=len(listing_pairs),
        massive_key_present=str(bool(api_key)).lower(),
        provider_usage_available="false",
    )
    out_root = storage.prices_root
    for window in windows:
        getattr(storage, str(WINDOWS[window]["storage_attr"])).mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "start": start,
        "end": end,
        "windows": windows,
        "config": portable_path(config_path.resolve()),
        "companies": [],
        "errors": [],
    }
    last_massive = 0.0
    fx_cache: dict[str, tuple[dict[str, float], dict[str, Any]]] = {}
    stats = {
        "processed": 0,
        "rows_written": 0,
        "massive_calls": 0,
        "yahoo_calls": 0,
        "errors": 0,
    }
    wanted_ids = {(id(company), id(listing)) for company, listing in listing_pairs}
    for company in companies:
        company_record = {
            "name": company.get("name"),
            "primary": company.get("primary"),
            "robinhood_symbol": company.get("robinhood_symbol"),
            "robinhood_status": company.get("robinhood_status"),
            "listings": [],
        }
        for listing in company.get("listings") or []:
            if (id(company), id(listing)) not in wanted_ids:
                continue
            symbol = str(listing["symbol"])
            market = str(listing.get("market") or "")
            listing_record = {
                "symbol": symbol,
                "market": market,
                "role": listing.get("role"),
                "windows": [],
            }
            for window in windows:
                window_start = window_start_date(window, start, end)
                if api_key and should_try_massive(symbol, market):
                    elapsed = time.monotonic() - last_massive
                    if elapsed < args.sleep:
                        wait = args.sleep - elapsed
                        reporter.emit(
                            "WAITING",
                            reason="provider_pacing",
                            wait_seconds=round(wait, 2),
                            symbol=symbol,
                            window=window,
                        )
                        time.sleep(wait)
                    last_massive = time.monotonic()
                try:
                    rows, meta = fetch_listing(symbol, market, window_start, end, api_key, window)
                    rows, conversion_meta = convert_rows_to_usd(rows, meta.get("currency") or "USD", fx_cache, window_start, end)
                    meta.update(conversion_meta)
                    window_dir = getattr(storage, str(WINDOWS[window]["storage_attr"]))
                    out_path = window_dir / f"{safe_symbol(symbol)}.json"
                    payload = {
                        "company": company.get("name"),
                        "symbol": symbol,
                        "market": market,
                        "role": listing.get("role"),
                        "window": window,
                        "from": window_start,
                        "to": end,
                        **meta,
                        "bars": rows,
                    }
                    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                    listing_record["windows"].append(
                        {
                            "window": window,
                            "provider": meta.get("provider"),
                            "provider_interval": meta.get("provider_interval"),
                            "rows": len(rows),
                            "currency": meta.get("currency"),
                            "path": portable_path(out_path),
                        }
                    )
                    stats["processed"] += 1
                    stats["rows_written"] += len(rows)
                    if meta.get("provider") == "massive":
                        stats["massive_calls"] += 1
                    elif meta.get("provider") == "yahoo_chart":
                        stats["yahoo_calls"] += 1
                    stats["errors"] = len(manifest["errors"])
                    reporter.checkpoint_stats(
                        stats,
                        processed=stats["processed"],
                        symbol=symbol,
                        window=window,
                        provider=meta.get("provider"),
                        rows=len(rows),
                    )
                except Exception as exc:
                    stats["processed"] += 1
                    error = {
                        "company": company.get("name"),
                        "symbol": symbol,
                        "market": market,
                        "window": window,
                        "error": str(exc),
                    }
                    manifest["errors"].append(error)
                    listing_record["windows"].append({**error, "rows": 0})
                    stats["errors"] = len(manifest["errors"])
                    reporter.emit("ERROR", symbol=symbol, window=window, market=market, error=str(exc))
                    reporter.checkpoint_stats(
                        stats,
                        processed=stats["processed"],
                        force=True,
                        symbol=symbol,
                        window=window,
                        error=str(exc),
                    )
            company_record["listings"].append(listing_record)
        manifest["companies"].append(company_record)

    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    reporter.done_stats(
        stats,
        companies=len(companies),
        listings=len(listing_pairs),
        windows=",".join(windows),
        manifest=portable_path(manifest_path),
    )
    return 0 if not manifest["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
