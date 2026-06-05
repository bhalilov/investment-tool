import json
import tempfile
import unittest
from pathlib import Path

from investment_tool.feeds.x.verify import verify_x_records


def base_record(**updates):
    record = {
        "conversation_id": "1",
        "created_at": "2026-06-04T12:00:00Z",
        "type": "FEED_THREAD",
        "analysis_stage": "captured_pending_ai_pass1",
        "tweets": [
            {"id": "1", "attachments": {"media_keys": ["3_1", "13_1"]}},
        ],
        "media": {
            "3_1": {"type": "photo"},
            "13_1": {"type": "animated_gif"},
        },
        "media_paths": {"3_1": "<data>/feeds/x/media/3_1.jpg"},
        "non_photo_media": [{"media_key": "13_1", "type": "animated_gif"}],
        "feed": {
            "feed_id": "x_research_account_001",
            "platform": "x",
            "username": "alojohhardcore",
            "user_id": "2033476611149066240",
        },
    }
    record.update(updates)
    return record


class XVerifyTests(unittest.TestCase):
    def write_record(self, records_dir: Path, name: str, payload: dict):
        records_dir.mkdir(parents=True, exist_ok=True)
        (records_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_clean_capture_record_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp)
            self.write_record(records_dir, "thread.json", base_record())

            result = verify_x_records(records_dir)

        self.assertEqual(result["records"], 1)
        self.assertEqual(result["violation_count"], 0)

    def test_global_media_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp)
            record = base_record(media_paths={"3_1": "ok.jpg", "3_2": "wrong.jpg"})
            self.write_record(records_dir, "thread.json", record)

            result = verify_x_records(records_dir)

        self.assertEqual(result["violation_count"], 1)
        self.assertEqual(result["violations"][0]["code"], "global_media_paths")

    def test_pending_capture_record_cannot_have_ai_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp)
            self.write_record(records_dir, "thread.json", base_record(signal="BUY_SIGNAL"))

            result = verify_x_records(records_dir)

        self.assertEqual(result["violation_count"], 1)
        self.assertEqual(result["violations"][0]["code"], "pending_record_has_ai_fields")

    def test_missing_feed_identity_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp)
            self.write_record(records_dir, "thread.json", base_record(feed={"feed_id": "x"}))

            result = verify_x_records(records_dir)

        codes = [item["code"] for item in result["violations"]]
        self.assertIn("missing_feed_identity", codes)

    def test_missing_photo_path_is_warning_not_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp)
            record = base_record(
                tweets=[{"id": "1", "attachments": {"media_keys": ["3_1"]}}],
                media={"3_1": {"type": "photo"}},
                media_paths={},
                non_photo_media=[],
            )
            self.write_record(records_dir, "thread.json", record)

            result = verify_x_records(records_dir)

        self.assertEqual(result["violation_count"], 0)
        self.assertEqual(result["warning_count"], 1)
        self.assertEqual(result["warnings"][0]["code"], "media_reference_without_path_or_placeholder")


if __name__ == "__main__":
    unittest.main()
