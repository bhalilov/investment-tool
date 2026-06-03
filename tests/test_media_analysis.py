import json
import tempfile
import unittest
from pathlib import Path

from investment_tool import media_analysis


class MediaAnalysisTests(unittest.TestCase):
    def test_iter_media_paths_only_returns_supported_images_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.png").write_bytes(b"png")
            (root / "a.jpg").write_bytes(b"jpg")
            (root / "c.txt").write_text("nope", encoding="utf-8")

            names = [path.name for path in media_analysis.iter_media_paths(root)]

        self.assertEqual(names, ["a.jpg", "b.png"])

    def test_media_output_path_uses_media_key(self):
        out = Path("/tmp/out")
        path = Path("/tmp/media/3_abc.jpg")

        self.assertEqual(media_analysis.media_output_path(out, path), out / "3_abc.json")

    def test_should_skip_when_existing_hash_matches_and_has_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "3_abc.jpg"
            image.write_bytes(b"image-content")
            out = root / "3_abc.json"
            out.write_text(
                json.dumps(
                    {
                        "file_sha256": media_analysis.media_fingerprint(image),
                        "analysis": {"summary": "done"},
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(media_analysis.should_skip(image, out, force=False))
            self.assertFalse(media_analysis.should_skip(image, out, force=True))

    def test_build_record_marks_visual_extraction_not_thread_judgment(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "3_abc.jpg"
            image.write_bytes(b"image-content")

            record = media_analysis.build_record(image, {"summary": "Visible chart."}, "gpt-5.5")

        self.assertEqual(record["media_key"], "3_abc")
        self.assertEqual(record["analysis_stage"], "media_visual_observation")
        self.assertEqual(record["authority"], "visual_extraction")
        self.assertTrue(record["ocr_or_description_only"])


if __name__ == "__main__":
    unittest.main()
