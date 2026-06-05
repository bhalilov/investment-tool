import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from investment_tool.feeds.x.store import (
    cleanup_old_json_versions,
    cleanup_old_render_versions,
    find_cached_thread_record,
    load_cached_threads,
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


if __name__ == "__main__":
    unittest.main()
