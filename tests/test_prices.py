import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from investment_tool.context import prices as market_prices


class PricesTests(unittest.TestCase):
    def test_safe_symbol_normalizes_provider_symbols_for_filenames(self):
        self.assertEqual(market_prices.safe_symbol("IFX.DE"), "IFX_DE")
        self.assertEqual(market_prices.safe_symbol("BRK/B"), "BRK_B")

    def test_usd_rows_are_marked_but_not_converted(self):
        rows = [{"date": "2026-03-02", "open": 10, "high": 12, "low": 9, "close": 11, "adjusted_close": 11}]

        converted, meta = market_prices.convert_rows_to_usd(rows, "USD", {}, "2026-03-01", "2026-03-03")

        self.assertFalse(meta["prices_converted_to_usd"])
        self.assertEqual(converted[0]["close"], 11)
        self.assertEqual(converted[0]["currency"], "USD")
        self.assertEqual(converted[0]["original_currency"], "USD")
        self.assertEqual(converted[0]["fx_rate_to_usd"], 1.0)

    def test_foreign_rows_are_converted_to_usd_and_preserve_original_values(self):
        rows = [
            {
                "date": "2026-03-02",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "adjusted_close": 104,
            }
        ]
        fx_cache = {
            "EUR": (
                {"2026-03-02": 1.2},
                {
                    "fx_provider": "fixture",
                    "fx_provider_symbol": "EURUSD=X",
                    "fx_direction": "direct",
                    "fx_currency": "EUR",
                    "fx_rows": 1,
                },
            )
        }

        converted, meta = market_prices.convert_rows_to_usd(rows, "EUR", fx_cache, "2026-03-01", "2026-03-03")

        self.assertTrue(meta["prices_converted_to_usd"])
        self.assertEqual(meta["original_currency"], "EUR")
        self.assertAlmostEqual(converted[0]["open"], 120)
        self.assertAlmostEqual(converted[0]["close"], 126)
        self.assertEqual(converted[0]["original_close"], 105)
        self.assertEqual(converted[0]["currency"], "USD")
        self.assertEqual(converted[0]["original_currency"], "EUR")
        self.assertEqual(converted[0]["fx_rate_to_usd"], 1.2)

    def test_missing_fx_rate_uses_previous_rate_and_records_gap(self):
        rows = [
            {"date": "2026-03-02", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100},
            {"date": "2026-03-03", "open": 200, "high": 200, "low": 200, "close": 200, "adjusted_close": 200},
        ]
        fx_cache = {
            "HKD": (
                {"2026-03-02": 0.125},
                {"fx_provider": "fixture", "fx_provider_symbol": "USDHKD=X", "fx_direction": "inverse", "fx_currency": "HKD"},
            )
        }

        converted, meta = market_prices.convert_rows_to_usd(rows, "HKD", fx_cache, "2026-03-01", "2026-03-03")

        self.assertEqual(meta["fx_missing_dates_filled"], ["2026-03-03"])
        self.assertAlmostEqual(converted[1]["close"], 25.0)
        self.assertEqual(converted[1]["original_close"], 200)

    def test_first_window_row_can_use_previous_cached_fx_rate(self):
        rows = [
            {"date": "2026-05-29", "open": 100, "high": 100, "low": 100, "close": 100, "adjusted_close": 100},
            {"date": "2026-06-01", "open": 200, "high": 200, "low": 200, "close": 200, "adjusted_close": 200},
        ]
        fx_cache = {
            "KRW": (
                {"2026-05-28": 0.00073, "2026-06-01": 0.00074},
                {"fx_provider": "fixture", "fx_provider_symbol": "USDKRW=X", "fx_direction": "inverse", "fx_currency": "KRW"},
            )
        }

        converted, meta = market_prices.convert_rows_to_usd(rows, "KRW", fx_cache, "2026-05-29", "2026-06-05")

        self.assertEqual(meta["fx_missing_dates_filled"], ["2026-05-29"])
        self.assertAlmostEqual(converted[0]["close"], 0.073)
        self.assertAlmostEqual(converted[1]["close"], 0.148)

    def test_timestamp_rows_are_converted_using_date_part(self):
        rows = [
            {
                "timestamp": "2026-06-04T14:30:00+00:00",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "adjusted_close": 105,
            }
        ]
        fx_cache = {
            "EUR": (
                {"2026-06-04": 1.1},
                {"fx_provider": "fixture", "fx_provider_symbol": "EURUSD=X", "fx_direction": "direct", "fx_currency": "EUR"},
            )
        }

        converted, _ = market_prices.convert_rows_to_usd(rows, "EUR", fx_cache, "2026-06-01", "2026-06-05")

        self.assertEqual(converted[0]["date"], "2026-06-04")
        self.assertEqual(converted[0]["timestamp"], "2026-06-04T14:30:00+00:00")
        self.assertAlmostEqual(converted[0]["close"], 115.5)

    def test_incremental_fetch_start_uses_latest_bar_with_overlap(self):
        payload = {
            "bars": [
                {"date": "2026-06-01", "close": 1},
                {"date": "2026-06-05", "close": 2},
            ]
        }

        self.assertEqual(
            market_prices.incremental_fetch_start(payload, "daily", "2026-03-01"),
            "2026-05-29",
        )

    def test_incremental_fresh_uses_synced_at_or_file_mtime(self):
        now = dt.datetime(2026, 6, 5, 17, 0, tzinfo=dt.timezone.utc)
        payload = {"synced_at": "2026-06-05T16:55:00+00:00", "bars": []}

        self.assertTrue(market_prices.is_incremental_fresh(payload, Path("/tmp/nope.json"), "intraday", now))
        self.assertFalse(market_prices.is_incremental_fresh(payload, Path("/tmp/nope.json"), "hourly", now + dt.timedelta(hours=2)))

    def test_merge_price_rows_dedupes_and_trims_window(self):
        existing = [
            {"date": "2026-05-28", "close": 1},
            {"date": "2026-06-01", "close": 2},
        ]
        incoming = [
            {"date": "2026-06-01", "close": 3},
            {"date": "2026-06-02", "close": 4},
        ]

        merged = market_prices.merge_price_rows(existing, incoming, "daily", "2026-06-01")

        self.assertEqual([row["date"] for row in merged], ["2026-06-01", "2026-06-02"])
        self.assertEqual(merged[0]["close"], 3)

    def test_window_start_dates_use_configured_lookbacks(self):
        self.assertEqual(market_prices.window_start_date("daily", "2026-03-01", "2026-06-05"), "2026-03-01")
        self.assertEqual(market_prices.window_start_date("hourly", "2026-03-01", "2026-06-05"), "2026-05-29")
        self.assertEqual(market_prices.window_start_date("intraday", "2026-03-01", "2026-06-05"), "2026-06-03")

    def test_selected_windows_deduplicates_or_defaults_to_all(self):
        self.assertEqual(market_prices.selected_windows(["daily", "daily", "hourly"]), ["daily", "hourly"])
        self.assertEqual(market_prices.selected_windows([]), ["daily", "hourly", "intraday"])

    def test_provider_rate_limit_wait_and_failure_are_stdout_events(self):
        def rate_limited(request, timeout=30):
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {},
                io.BytesIO(b'{"error":"rate limited"}'),
            )

        stdout = io.StringIO()
        with (
            patch("urllib.request.urlopen", side_effect=rate_limited),
            patch("time.sleep") as sleep,
            contextlib.redirect_stdout(stdout),
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                market_prices.request_json("https://provider.example/prices?apiKey=hidden", retries=2)

        output = stdout.getvalue()
        self.assertIn("WAITING", output)
        self.assertIn("reason=provider_rate_limit", output)
        self.assertIn("ERROR", output)
        self.assertIn("reason=request_failed", output)
        self.assertIn("url=https://provider.example/prices", output)
        self.assertEqual(sleep.call_count, 1)

    def test_incremental_skips_fresh_existing_price_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "start_date": "2026-03-01",
                        "companies": [
                            {
                                "name": "Test",
                                "primary": "TEST",
                                "listings": [{"symbol": "TEST", "market": "US", "role": "primary"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = root / "context" / "prices" / "intraday" / "TEST.json"
            out.parent.mkdir(parents=True)
            out.write_text(
                json.dumps(
                    {
                        "synced_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "provider": "fixture",
                        "provider_interval": "15/minute",
                        "currency": "USD",
                        "bars": [{"date": "2026-06-05", "timestamp": "2026-06-05T16:45:00+00:00", "close": 1}],
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with (
                patch.object(market_prices, "fetch_listing", side_effect=AssertionError("should not fetch")),
                contextlib.redirect_stdout(stdout),
            ):
                code = market_prices.main(
                    [
                        "--config",
                        str(config),
                        "--data-dir",
                        str(root),
                        "--window",
                        "intraday",
                        "--incremental",
                        "--env",
                        str(root / "missing.env"),
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("status=skipped_fresh", stdout.getvalue())

    def test_fetch_from_override_preserves_existing_daily_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "start_date": "2026-03-01",
                        "companies": [
                            {
                                "name": "Test",
                                "primary": "TEST",
                                "listings": [{"symbol": "TEST", "market": "US", "role": "primary"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = root / "context" / "prices" / "daily" / "TEST.json"
            out.parent.mkdir(parents=True)
            out.write_text(
                json.dumps(
                    {
                        "synced_at": "2026-06-04T20:00:00+00:00",
                        "provider": "fixture",
                        "provider_interval": "1/day",
                        "currency": "USD",
                        "bars": [
                            {"date": "2026-06-03", "close": 1},
                            {"date": "2026-06-04", "close": 2},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_fetch(symbol, market, start, end, api_key, window):
                self.assertEqual((symbol, market, start, end, window), ("TEST", "US", "2026-06-05", "2026-06-05", "daily"))
                return [{"date": "2026-06-05", "open": 3, "high": 3, "low": 3, "close": 3, "adjusted_close": 3}], {
                    "provider": "fixture",
                    "provider_interval": "1/day",
                    "currency": "USD",
                }

            with (
                patch.object(market_prices, "fetch_listing", side_effect=fake_fetch),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = market_prices.main(
                    [
                        "--config",
                        str(config),
                        "--data-dir",
                        str(root),
                        "--window",
                        "daily",
                        "--incremental",
                        "--fetch-from",
                        "2026-06-05",
                        "--from",
                        "2026-03-01",
                        "--to",
                        "2026-06-05",
                        "--env",
                        str(root / "missing.env"),
                    ]
                )

            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["fetch_from"], "2026-06-05")
        self.assertEqual(payload["from"], "2026-03-01")
        self.assertEqual([row["date"] for row in payload["bars"]], ["2026-06-03", "2026-06-04", "2026-06-05"])


if __name__ == "__main__":
    unittest.main()
