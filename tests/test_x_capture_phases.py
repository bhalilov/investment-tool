import json
import tempfile
import unittest
from pathlib import Path

from investment_tool.feeds.x.api import ConversationSearchResult
from investment_tool.feeds.x.capture import (
    XCaptureOptions,
    XMediaDownloadResult,
    XRecordWriteResult,
    assemble_conversations,
    cached_conversation_needs_search,
    discover_conversation_ids,
    has_new_tweets,
    source_completeness_payload,
    write_capture_manifest,
)
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

    def test_incremental_discovery_uses_only_uncached_seed_conversations(self):
        context = capture_context()
        tweets = {
            "cached": {"id": "cached", "author_id": "feed-user", "conversation_id": "c1", "created_at": "2026-06-04T04:00:00Z"},
            "new-reply": {"id": "new-reply", "author_id": "feed-user", "conversation_id": "c1", "created_at": "2026-06-04T05:00:00Z"},
            "other": {"id": "other", "author_id": "other-user", "conversation_id": "c2", "created_at": "2026-06-04T06:00:00Z"},
            "new-root": {"id": "new-root", "author_id": "feed-user", "conversation_id": "c3", "created_at": "2026-06-04T07:00:00Z"},
        }

        result = discover_conversation_ids(
            tweets,
            XCaptureOptions(max_threads=5, incremental=True),
            context,
            seed_ids=["cached", "new-reply", "other", "new-root"],
            cached_tweet_ids={"c1": {"cached"}},
        )

        self.assertEqual(result, ["c1", "c3"])

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

    def test_source_completeness_marks_missing_root_and_references(self):
        items = [
            {
                "id": "reply",
                "conversation_id": "root",
                "referenced_tweets": [{"type": "replied_to", "id": "root"}, {"type": "quoted", "id": "missing-quote"}],
            }
        ]
        search_result = ConversationSearchResult(
            result_count=30,
            pages_requested=1,
            pages_fetched=1,
            has_more=False,
            missing_reference_ids=("root",),
            error_count=1,
        )

        payload = source_completeness_payload("root", None, items, {"reply": items[0]}, search_result)

        self.assertEqual(payload["status"], "api_partial_missing_references")
        self.assertTrue(payload["missing_root_tweet"])
        self.assertEqual(payload["missing_reference_ids"], ["missing-quote", "root"])
        self.assertEqual(payload["conversation_search"]["result_count"], 30)

    def test_source_completeness_marks_page_limited_search(self):
        root = {"id": "root", "conversation_id": "root"}
        search_result = ConversationSearchResult(
            result_count=100,
            pages_requested=1,
            pages_fetched=1,
            has_more=True,
        )

        payload = source_completeness_payload("root", root, [root], {"root": root}, search_result)

        self.assertEqual(payload["status"], "conversation_search_limited")
        self.assertFalse(payload["missing_root_tweet"])

    def test_source_completeness_marks_exhausted_complete_search(self):
        root = {"id": "root", "conversation_id": "root"}
        search_result = ConversationSearchResult(
            result_count=12,
            pages_requested=5,
            pages_fetched=1,
            has_more=False,
        )

        payload = source_completeness_payload("root", root, [root], {"root": root}, search_result)

        self.assertEqual(payload["status"], "conversation_search_exhausted")

    def test_cached_page_limited_conversation_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp)
            (records / "thread__root.json").write_text(
                json.dumps(
                    {
                        "conversation_id": "root",
                        "source_completeness": {
                            "conversation_search": {
                                "has_more": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(cached_conversation_needs_search(records, "root"))

    def test_cached_exhausted_conversation_can_be_skipped_when_no_new_tweets(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp)
            (records / "thread__root.json").write_text(
                json.dumps(
                    {
                        "conversation_id": "root",
                        "source_completeness": {
                            "conversation_search": {
                                "has_more": False,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertFalse(cached_conversation_needs_search(records, "root"))

    def test_capture_manifest_separates_changed_cached_and_description_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw" / "run"
            raw.mkdir(parents=True)
            result = XRecordWriteResult(
                entries=[{"conversation_id": "changed"}, {"conversation_id": "cached"}],
                ignored=1,
                changed_conversation_ids={"changed"},
                cached_conversation_ids={"cached"},
                ignored_conversation_ids={"ignored"},
            )
            media = XMediaDownloadResult(
                media_paths={"m1": "<data>/feeds/x/media/m1.jpg", "m2": "<data>/feeds/x/media/m2.jpg"},
                downloaded_media_keys={"m1"},
                requested_media_keys={"m1", "m2"},
            )

            manifest = write_capture_manifest(
                root,
                "run",
                raw,
                result.entries,
                ["changed", "cached"],
                {"cached", "old"},
                result,
                media,
                {"m2"},
                {"m2": {"cached"}},
                {"api_calls": 3, "unique_post_ids_returned": 7, "estimated_cost_usd": 0.035},
                result.ignored,
            )

        self.assertEqual(manifest["changed_conversation_ids"], ["changed"])
        self.assertEqual(manifest["discovered_conversation_ids"], ["cached", "changed"])
        self.assertEqual(manifest["loaded_cached_conversations"], 2)
        self.assertEqual(manifest["cached_conversation_ids"], ["cached"])
        self.assertEqual(manifest["ignored_conversation_ids"], ["ignored"])
        self.assertEqual(manifest["downloaded_media_keys"], ["m1"])
        self.assertEqual(manifest["description_candidate_media_keys"], ["m2"])
        self.assertEqual(manifest["render_conversation_ids"], ["cached", "changed", "ignored"])


if __name__ == "__main__":
    unittest.main()
