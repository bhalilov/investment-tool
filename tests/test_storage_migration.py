import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from investment_tool.cli import main as cli_main
from investment_tool.runtime.paths import portable_path, resolve_portable_path, storage_paths


class StorageMigrationTests(unittest.TestCase):
    def call_cli(self, args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli_main.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_storage_paths_use_canonical_names(self):
        root = Path("/tmp/runtime-data")
        paths = storage_paths(root)

        self.assertEqual(paths.x_records, root / "sources" / "x" / "records")
        self.assertEqual(paths.prices_daily, root / "context" / "prices" / "daily")
        self.assertEqual(paths.indexes, root / "presentation" / "indexes")
        self.assertEqual(paths.legacy_x_evidence, root / "retrieval" / "legacy" / "x" / "evidence")

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
            path = root / "sources" / "x" / "media" / "3_abc.jpg"

            token = portable_path(path, root)

            self.assertEqual(token, "<data>/sources/x/media/3_abc.jpg")
            self.assertEqual(resolve_portable_path(token, root), path)

    def test_storage_migrate_moves_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_records = root / "x_threads" / "thread_json"
            old_records.mkdir(parents=True)
            (old_records / "thread.json").write_text(
                json.dumps({"media_paths": {"3_abc": str(root / "x_threads" / "media" / "3_abc.jpg")}}) + "\n",
                encoding="utf-8",
            )
            old_media = root / "x_threads" / "media"
            old_media.mkdir(parents=True)
            (old_media / "3_abc.jpg").write_bytes(b"image")
            old_prices = root / "market_prices"
            old_prices.mkdir()
            (old_prices / "manifest.json").write_text('{"prices": true}\n', encoding="utf-8")

            code, stdout, stderr = self.call_cli(["storage", "migrate", "--apply", "--data-dir", str(root)])

            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("FAILED=0", stdout)
            written = json.loads((root / "sources" / "x" / "records" / "thread.json").read_text(encoding="utf-8"))
            self.assertEqual(written["media_paths"]["3_abc"], "<data>/sources/x/media/3_abc.jpg")
            self.assertTrue((root / "context" / "prices" / "manifest.json").exists())
            self.assertFalse((root / "x_threads").exists())
            self.assertFalse((root / "market_prices").exists())
            self.assertTrue((root / "README.md").exists())
            self.assertTrue((root / "sources" / "x" / "README.md").exists())

            code, stdout, stderr = self.call_cli(["storage", "migrate", "--verify-only", "--data-dir", str(root)])

            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("FAILED=0", stdout)
            self.assertIn("ALREADY_MIGRATED=", stdout)
            manifest = json.loads((root / "workflow" / "migrations" / "storage_migration_manifest.json").read_text())
            self.assertEqual(manifest["summary"]["failed"], 0)
            self.assertEqual(manifest["summary"]["readme_missing_or_stale"], 0)

    def test_storage_migrate_dry_run_does_not_create_target_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_records = root / "x_threads" / "thread_json"
            old_records.mkdir(parents=True)
            (old_records / "thread.json").write_text('{"ok": true}\n', encoding="utf-8")

            code, stdout, stderr = self.call_cli(["storage", "migrate", "--dry-run", "--data-dir", str(root)])

            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("STORAGE_MIGRATION_MODE=dry_run", stdout)
            self.assertFalse((root / "sources").exists())

    def test_storage_clean_old_deletes_only_legacy_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "sources" / "x" / "records"
            active.mkdir(parents=True)
            (active / "thread.json").write_text('{"active": true}\n', encoding="utf-8")
            old_targets = [
                root / "legacy" / "unsorted" / "old.txt",
                root / "sources" / "x" / "rebuild" / "old.json",
                root / "sources" / "x" / "backups" / "backup.json",
                root / "retrieval" / "legacy" / "x" / "evidence" / "old.md",
            ]
            for path in old_targets:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("old\n", encoding="utf-8")

            code, stdout, stderr = self.call_cli(["storage", "clean-old", "--apply", "--data-dir", str(root)])

            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("DELETED=4", stdout)
            self.assertTrue((active / "thread.json").exists())
            self.assertFalse((root / "legacy").exists())
            self.assertFalse((root / "sources" / "x" / "rebuild").exists())
            self.assertFalse((root / "sources" / "x" / "backups").exists())
            self.assertFalse((root / "retrieval" / "legacy").exists())


if __name__ == "__main__":
    unittest.main()
