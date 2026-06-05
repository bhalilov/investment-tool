import contextlib
import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from investment_tool.feeds.x.api import XClient, fetch_timeline


class XApiTests(unittest.TestCase):
    def test_fetch_timeline_stops_after_known_streak(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def get(self, path, params, label):
                self.calls += 1
                return {
                    "data": [
                        {"id": "new", "author_id": "feed", "conversation_id": "new"},
                        {"id": "known-1", "author_id": "feed", "conversation_id": "old"},
                        {"id": "known-2", "author_id": "feed", "conversation_id": "old"},
                        {"id": "too-old", "author_id": "feed", "conversation_id": "older"},
                    ],
                    "meta": {"next_token": "next"},
                }

        tweets = {}
        client = FakeClient()

        seeds = fetch_timeline(
            client,
            "feed-user",
            3,
            tweets,
            {},
            {},
            known_tweet_ids={"known-1", "known-2"},
            stop_after_known_streak=2,
        )

        self.assertEqual(seeds, ["new", "known-1"])
        self.assertEqual(client.calls, 1)
        self.assertIn("too-old", tweets)

    def test_rate_limit_retry_is_capped_and_reported_to_stdout(self):
        def rate_limited(request, timeout=30):
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"x-rate-limit-reset": "0"},
                io.BytesIO(b'{"title":"rate limited"}'),
            )

        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            stdout = io.StringIO()
            with (
                patch.dict(os.environ, {"X_MAX_RATE_LIMIT_RETRIES": "1"}),
                patch("urllib.request.urlopen", side_effect=rate_limited),
                patch("time.sleep") as sleep,
                contextlib.redirect_stdout(stdout),
            ):
                client = XClient("token", raw_dir)
                with self.assertRaisesRegex(RuntimeError, "rate limit retry limit"):
                    client.get("/tweets", {}, "unit_rate_limit")

        output = stdout.getvalue()
        self.assertIn("WAITING", output)
        self.assertIn("reason=rate_limit", output)
        self.assertIn("ERROR", output)
        self.assertIn("reason=rate_limit_retries_exhausted", output)
        self.assertEqual(sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
