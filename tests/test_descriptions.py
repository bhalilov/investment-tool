import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_tool.context import descriptions as media_analysis


class DescriptionsTests(unittest.TestCase):
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

    def test_media_paths_for_keys_resolves_directly_without_full_scan_order_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wanted.png").write_bytes(b"png")
            (root / "other.jpg").write_bytes(b"jpg")

            paths = media_analysis.media_paths_for_keys(root, {"wanted", "missing"})

        self.assertEqual([path.name for path in paths], ["wanted.png"])

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

    def test_analysis_failure_is_reported_immediately_to_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media_dir = root / "media"
            out_dir = root / "out"
            media_dir.mkdir()
            image = media_dir / "3_abc.jpg"
            image.write_bytes(b"image-content")
            args = [
                "--media-dir",
                str(media_dir),
                "--output-dir",
                str(out_dir),
                "--env",
                str(root / "missing.env"),
                "--limit",
                "1",
            ]
            stdout = io.StringIO()
            with (
                patch.object(media_analysis, "analyze_media_with_openai", side_effect=RuntimeError("boom")),
                contextlib.redirect_stdout(stdout),
            ):
                code = media_analysis.main(args)

        output = stdout.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("WAITING", output)
        self.assertIn("reason=openai_media_analysis", output)
        self.assertIn("ERROR", output)
        self.assertIn("error=boom", output)


if __name__ == "__main__":
    unittest.main()
