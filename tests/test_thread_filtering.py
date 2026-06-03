import unittest

from investment_tool import thread_filtering


def text_of(item):
    return item.get("text", "")


def no_links(_item):
    return []


def media_keys(item):
    return item.get("media_keys", [])


class ThreadFilteringTests(unittest.TestCase):
    def test_ignore_source_reply_without_ticker_finance_link_or_media(self):
        config = thread_filtering.ThreadFilterConfig(
            source_user_id="source",
            source_reply_label="SOURCE_REPLY_CONTEXT",
        )
        root = {"id": "1", "author_id": "other", "text": "hello"}
        items = [{"id": "2", "author_id": "source", "text": "thanks"}]

        reason = thread_filtering.ignore_reason(
            root,
            items,
            "SOURCE_REPLY_CONTEXT",
            [],
            config,
            text_of,
            lambda _item: False,
            no_links,
            media_keys,
        )

        self.assertEqual(reason, "OFF_TOPIC_REPLY_CONTEXT")

    def test_media_keeps_no_ticker_reply_relevant(self):
        config = thread_filtering.ThreadFilterConfig(
            source_user_id="source",
            source_reply_label="SOURCE_REPLY_CONTEXT",
        )
        root = {"id": "1", "author_id": "other", "text": "look"}
        items = [{"id": "2", "author_id": "source", "text": "see chart", "media_keys": ["m1"]}]

        reason = thread_filtering.ignore_reason(
            root,
            items,
            "SOURCE_REPLY_CONTEXT",
            [],
            config,
            text_of,
            lambda _item: False,
            no_links,
            media_keys,
        )

        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
