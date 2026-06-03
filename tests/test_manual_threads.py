import json
import tempfile
import unittest
from pathlib import Path

from investment_tool import manual_threads


def tiny_png(width: int = 2, height: int = 3) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


class ManualThreadsTests(unittest.TestCase):
    def test_image_size_reads_png_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screen.png"
            path.write_bytes(tiny_png(7, 11))

            self.assertEqual(manual_threads.image_size(path), (7, 11))

    def test_build_bundle_record_keeps_order_and_marks_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.png"
            second = root / "b.png"
            first.write_bytes(tiny_png())
            second.write_bytes(tiny_png())

            record = manual_threads.build_bundle_record(
                bundle_id="sample",
                bundle_name="Sample",
                sources=[first, second],
                output_dir=root / "out",
                dry_run=True,
            )

        self.assertEqual(record["source_type"], "manual_x_screenshot_bundle")
        self.assertEqual([item["index"] for item in record["screenshots"]], [1, 2])
        self.assertIsNone(record["screenshots"][0]["duplicate_of_index"])
        self.assertEqual(record["screenshots"][1]["duplicate_of_index"], 1)
        self.assertEqual(record["analysis_stage"], "imported_pending_reconstruction")

    def test_write_bundle_copies_images_and_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "screen.png"
            source.write_bytes(tiny_png())
            out = root / "manual"
            record = manual_threads.build_bundle_record(
                bundle_id="sample",
                bundle_name="Sample",
                sources=[source],
                output_dir=out,
                dry_run=False,
            )

            bundle_path = manual_threads.write_bundle(record, [source], out, force=False)
            written = json.loads(bundle_path.read_text(encoding="utf-8"))
            imported_path = Path(written["screenshots"][0]["imported_path"])
            bundle_exists = bundle_path.exists()
            imported_exists = imported_path.exists()
            imported_bytes = imported_path.read_bytes()

        self.assertTrue(bundle_exists)
        self.assertTrue(imported_exists)
        self.assertEqual(imported_bytes, tiny_png())

    def test_reconstruction_prompt_mentions_stitching_and_embedded_media(self):
        record = {
            "bundle_id": "sample",
            "screenshots": [
                {
                    "index": 1,
                    "original_filename": "one.png",
                    "width": 768,
                    "height": 1024,
                    "embedded_datetime": "2026:05:31 14:24:34",
                }
            ],
        }

        prompt = manual_threads.build_reconstruction_prompt(record)

        self.assertIn("logically stitch screenshots into scroll groups", prompt)
        self.assertIn("Images embedded inside visible X posts are embedded media", prompt)


if __name__ == "__main__":
    unittest.main()
