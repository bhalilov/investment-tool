import unittest

from investment_tool import market_prices


class MarketPriceTests(unittest.TestCase):
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
                    "fx_source": "fixture",
                    "fx_source_symbol": "EURUSD=X",
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
                {"fx_source": "fixture", "fx_source_symbol": "USDHKD=X", "fx_direction": "inverse", "fx_currency": "HKD"},
            )
        }

        converted, meta = market_prices.convert_rows_to_usd(rows, "HKD", fx_cache, "2026-03-01", "2026-03-03")

        self.assertEqual(meta["fx_missing_dates_filled"], ["2026-03-03"])
        self.assertAlmostEqual(converted[1]["close"], 25.0)
        self.assertEqual(converted[1]["original_close"], 200)


if __name__ == "__main__":
    unittest.main()
