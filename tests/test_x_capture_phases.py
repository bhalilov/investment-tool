import unittest

from investment_tool.feeds.x.capture import XCaptureOptions, assemble_conversations, discover_conversation_ids, has_new_tweets
from investment_tool.feeds.x.context import XCaptureContext
from investment_tool.runtime.config import FeedProfile


def capture_context() -> XCaptureContext:
    return XCaptureContext(
        profile=FeedProfile(
            feed_id="test_feed",
            platform="x",
            module="x-capture",
            username="source",
            user_id="feed-user",
            display_name="Source",
            data_root="",
            alternate_usernames=(),
            thread_rules_path="",
            media_rules_path="",
            user_specifics={},
        ),
        thread_rules={},
        media_rules={},
    )


class XCapturePhaseTests(unittest.TestCase):
    def test_discovers_newest_feed_authored_conversations(self):
        context = capture_context()
        tweets = {
            "other": {"id": "other", "author_id": "other-user", "conversation_id": "c3", "created_at": "2026-06-04T03:00:00Z"},
            "older": {"id": "older", "author_id": "feed-user", "conversation_id": "c1", "created_at": "2026-06-04T01:00:00Z"},
            "newer": {"id": "newer", "author_id": "feed-user", "conversation_id": "c2", "created_at": "2026-06-04T04:00:00Z"},
            "duplicate": {"id": "duplicate", "author_id": "feed-user", "conversation_id": "c2", "created_at": "2026-06-04T02:00:00Z"},
        }

        result = discover_conversation_ids(tweets, XCaptureOptions(max_threads=2), context)

        self.assertEqual(result, ["c2", "c1"])

    def test_explicit_conversation_id_bypasses_discovery(self):
        context = capture_context()

        result = discover_conversation_ids({}, XCaptureOptions(conversation_id="wanted"), context)

        self.assertEqual(result, ["wanted"])

    def test_has_new_tweets_compares_current_conversation_to_cache(self):
        tweets = {
            "a": {"id": "a", "conversation_id": "c1"},
            "b": {"id": "b", "conversation_id": "c1"},
            "c": {"id": "c", "conversation_id": "c2"},
        }

        self.assertFalse(has_new_tweets("c1", tweets, {"c1": {"a", "b"}}))
        self.assertTrue(has_new_tweets("c1", tweets, {"c1": {"a"}}))

    def test_assemble_conversations_includes_feed_quoted_context_only(self):
        context = capture_context()
        tweets = {
            "root": {
                "id": "root",
                "author_id": "feed-user",
                "conversation_id": "root",
                "referenced_tweets": [{"type": "quoted", "id": "quoted"}],
            },
            "reply": {
                "id": "reply",
                "author_id": "other-user",
                "conversation_id": "root",
                "referenced_tweets": [{"type": "quoted", "id": "other-quoted"}],
            },
            "quoted": {"id": "quoted", "author_id": "someone", "conversation_id": "elsewhere"},
            "other-quoted": {"id": "other-quoted", "author_id": "someone", "conversation_id": "elsewhere"},
        }

        conversations = assemble_conversations(tweets, ["root"], context)
        ids = {tweet["id"] for tweet in conversations["root"]}

        self.assertEqual(ids, {"root", "reply", "quoted"})


if __name__ == "__main__":
    unittest.main()
