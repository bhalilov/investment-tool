import os
import tempfile
import unittest
from pathlib import Path

from investment_tool.runtime.paths import portable_path, resolve_portable_path, storage_paths


class RuntimePathTests(unittest.TestCase):
    def test_storage_paths_use_canonical_names(self):
        root = Path("/tmp/runtime-data")
        paths = storage_paths(root)

        self.assertEqual(paths.x_records, root / "feeds" / "x" / "records")
        self.assertEqual(paths.prices_daily, root / "context" / "prices" / "daily")
        self.assertEqual(paths.articles_evidence, root / "feeds" / "articles" / "evidence")
        self.assertEqual(paths.indexes, root / "presentation" / "indexes")

    def test_storage_paths_resolve_relative_to_project_home(self):
        old_home = os.environ.get("INVESTMENT_TOOL_HOME")
        old_data = os.environ.get("INVESTMENT_TOOL_DATA_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["INVESTMENT_TOOL_HOME"] = tmp
            os.environ["INVESTMENT_TOOL_DATA_DIR"] = "runtime"
            try:
                self.assertEqual(storage_paths().root, (Path(tmp) / "runtime").resolve())
            finally:
                if old_home is None:
                    os.environ.pop("INVESTMENT_TOOL_HOME", None)
                else:
                    os.environ["INVESTMENT_TOOL_HOME"] = old_home
                if old_data is None:
                    os.environ.pop("INVESTMENT_TOOL_DATA_DIR", None)
                else:
                    os.environ["INVESTMENT_TOOL_DATA_DIR"] = old_data

    def test_portable_path_round_trips_data_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "feeds" / "x" / "media" / "3_abc.jpg"

            token = portable_path(path, root)

            self.assertEqual(token, "<data>/feeds/x/media/3_abc.jpg")
            self.assertEqual(resolve_portable_path(token, root), path)


if __name__ == "__main__":
    unittest.main()
