import contextlib
import io
import unittest
import urllib.error
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


if __name__ == "__main__":
    unittest.main()
