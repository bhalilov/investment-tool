import json
import tempfile
import unittest
from pathlib import Path

from investment_tool import capture_threads


class CaptureThreadsRawRebuildTests(unittest.TestCase):
    def test_load_raw_archive_reads_wrapped_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw_api" / "run"
            raw_dir.mkdir(parents=True)
            (raw_dir / "0001_conversation-1-page-1_200.json").write_text(
                json.dumps(
                    {
                        "status": 200,
                        "response": {
                            "data": [
                                {
                                    "id": "1",
                                    "conversation_id": "1",
                                    "author_id": "2033476611149066240",
                                    "text": "Chart",
                                    "attachments": {"media_keys": ["3_1"]},
                                }
                            ],
                            "includes": {
                                "users": [{"id": "2033476611149066240", "username": "alojohhardcore"}],
                                "media": [{"media_key": "3_1", "type": "photo", "url": "https://example.test/a.jpg"}],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            tweets, users, media, stats = capture_threads.load_raw_api_archive(Path(tmp) / "raw_api")

        self.assertIn("1", tweets)
        self.assertIn("2033476611149066240", users)
        self.assertIn("3_1", media)
        self.assertEqual(stats["raw_files"], 1)

    def test_existing_media_paths_keys_by_file_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_dir = Path(tmp)
            (media_dir / "3_1.jpg").write_bytes(b"image")
            (media_dir / "3_2.png").write_bytes(b"image")

            paths = capture_threads.existing_local_media_paths(media_dir)

        self.assertEqual(set(paths), {"3_1", "3_2"})

    def test_missing_media_keys_marks_absent_local_files(self):
        items = [{"attachments": {"media_keys": ["3_1", "3_2"]}}]
        media = {"3_1": {"type": "photo"}, "3_2": {"type": "video"}}

        missing = capture_threads.missing_media_keys(items, media, {"3_1": "/tmp/3_1.jpg"})

        self.assertEqual(missing, [{"media_key": "3_2", "type": "video", "has_metadata": True, "reason": "not_downloaded_or_unavailable"}])


if __name__ == "__main__":
    unittest.main()
