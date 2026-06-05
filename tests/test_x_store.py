import tempfile
import unittest
from pathlib import Path

from investment_tool.feeds.x.store import cleanup_old_json_versions


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


if __name__ == "__main__":
    unittest.main()
