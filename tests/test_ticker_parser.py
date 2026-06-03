import unittest

from investment_tool import ticker_parser


class TickerParserTests(unittest.TestCase):
    def test_single_explicit_ticker_bucket_is_primary(self):
        self.assertEqual(ticker_parser.ticker_bucket_payload(["MU"]), {"primary_ticker": "MU"})

    def test_multiple_op_tickers_are_mentioned_only(self):
        self.assertEqual(
            ticker_parser.ticker_bucket_payload(["MU", "NVDA"]),
            {"mentioned_only_tickers": ["MU", "NVDA"]},
        )

    def test_company_alias_maps_to_symbol(self):
        self.assertIn("TSLA", ticker_parser.extract_tickers("Tesla is moving."))


if __name__ == "__main__":
    unittest.main()
