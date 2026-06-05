import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_tool.feeds.x.store import (
    cleanup_old_json_versions,
    cleanup_old_render_versions,
    find_cached_thread_record,
    load_cached_threads,
    rerender_cached_threads,
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


class XStoreTests(unittest.TestCase):
    def test_capture_json_cleanup_does_not_touch_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "records"
            html = root / "html"
            records.mkdir()
            html.mkdir()
            keep = records / "new__123.json"
            old = records / "old__123.json"
            page = html / "old__123.html"
            keep.write_text("{}", encoding="utf-8")
            old.write_text("{}", encoding="utf-8")
            page.write_text("<html></html>", encoding="utf-8")

            cleanup_old_json_versions(records, "123", keep)

            self.assertTrue(keep.exists())
            self.assertFalse(old.exists())
            self.assertTrue(page.exists())

    def test_render_cleanup_removes_old_json_and_html_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "records"
            html = root / "html"
            records.mkdir()
            html.mkdir()
            keep_json = records / "new-title__123.json"
            old_json = records / "old-title__123.json"
            keep_html = html / "new-title__123.html"
            old_html = html / "old-title__123.html"
            orphan_html = html / "older-title__123.html"
            keep_json.write_text("{}", encoding="utf-8")
            old_json.write_text('{"canonical_filename": "old-title__123.html"}', encoding="utf-8")
            keep_html.write_text("<html>new</html>", encoding="utf-8")
            old_html.write_text("<html>old</html>", encoding="utf-8")
            orphan_html.write_text("<html>orphan</html>", encoding="utf-8")

            cleanup_old_render_versions(records, html, "123", keep_json, keep_html)

            self.assertTrue(keep_json.exists())
            self.assertTrue(keep_html.exists())
            self.assertFalse(old_json.exists())
            self.assertFalse(old_html.exists())
            self.assertFalse(orphan_html.exists())

    def test_load_cached_threads_reports_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp)
            (records / "bad.json").write_text("{not json", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                cached = load_cached_threads(records, {}, {}, {})

        output = stdout.getvalue()
        self.assertEqual(cached, {})
        self.assertIn("WARNING", output)
        self.assertIn("reason=json_read_failed", output)
        self.assertIn("action=load_cached_threads", output)
        self.assertIn("bad.json", output)

    def test_find_cached_thread_record_reports_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp)
            (records / "bad__123.json").write_text("{not json", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                record = find_cached_thread_record(records, "123")

        output = stdout.getvalue()
        self.assertIsNone(record)
        self.assertIn("WARNING", output)
        self.assertIn("reason=json_read_failed", output)
        self.assertIn("action=find_cached_thread_record", output)
        self.assertIn("bad__123.json", output)

    def test_rerender_cached_threads_can_limit_to_selected_conversations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "records"
            html = root / "html"
            presentation = root / "presentation"
            records.mkdir()
            html.mkdir()
            (presentation / "indexes").mkdir(parents=True)
            for conv_id in ("c1", "c2"):
                filename = f"20260604__UNKNOWN__title__{conv_id}.html"
                (html / filename).write_text("<html></html>", encoding="utf-8")
                (records / f"20260604__UNKNOWN__title__{conv_id}.json").write_text(
                    (
                        "{"
                        f'"conversation_id": "{conv_id}",'
                        f'"canonical_filename": "{filename}",'
                        '"title": "Title",'
                        '"type": "feed_post",'
                        '"primary_label": "UNKNOWN",'
                        '"tickers": [],'
                        '"tags": [],'
                        f'"tweets": [{{"id": "{conv_id}", "author_id": "feed-user", "conversation_id": "{conv_id}", "created_at": "2026-06-04T00:00:00Z", "text": "hello"}}],'
                        '"users": {},'
                        '"media": {},'
                        '"media_paths": {}'
                        "}"
                    ),
                    encoding="utf-8",
                )
            rendered = []

            def fake_render(path, *args, **kwargs):
                rendered.append(path.name)
                path.write_text("<html>rendered</html>", encoding="utf-8")

            with patch("investment_tool.feeds.x.store.render_thread_html", side_effect=fake_render):
                entries = rerender_cached_threads(root, records, html, None, capture_context(), presentation, conversation_ids={"c1"})

        self.assertEqual(len(rendered), 1)
        self.assertIn("__c1.html", rendered[0])
        self.assertEqual({entry["conversation_id"] for entry in entries}, {"c1", "c2"})


if __name__ == "__main__":
    unittest.main()
