import json
import tempfile
import unittest
from pathlib import Path

from investment_tool.presentation.threads import render_thread_html


class ThreadPresentationTests(unittest.TestCase):
    def test_render_thread_html_includes_media_description_for_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            presentation = root / "presentation"
            page = presentation / "threads" / "x" / "thread.html"
            page.parent.mkdir(parents=True)
            description_dir = root / "context" / "descriptions" / "x"
            description_dir.mkdir(parents=True)
            media_file = root / "feeds" / "x" / "media" / "3_abc.jpg"
            media_file.parent.mkdir(parents=True)
            media_file.write_bytes(b"image")
            (description_dir / "3_abc.json").write_text(
                json.dumps(
                    {
                        "model": "gpt-5.5",
                        "analyzed_at": "2026-06-05T00:00:00Z",
                        "analysis": {
                            "visual_type": "stock_chart",
                            "summary": "Visible chart for Tesla.",
                            "detected_tickers": ["TSLA"],
                            "detected_companies": ["Tesla"],
                            "visible_text": ["TSLA", "$300"],
                            "key_numbers": ["$300"],
                            "dates_or_timeframes": ["2026"],
                            "chart_or_table_summary": "Line chart trends upward.",
                            "uncertainties": [],
                            "confidence": "HIGH",
                        },
                    }
                ),
                encoding="utf-8",
            )

            render_thread_html(
                page,
                "root",
                "Title",
                "aj_thread",
                "TSLA",
                ["TSLA"],
                [],
                "",
                {"analysis_stage": "captured_pending_ai_pass1"},
                root / "feeds" / "x" / "records" / "root.json",
                [
                    {
                        "id": "root",
                        "author_id": "user-1",
                        "conversation_id": "root",
                        "created_at": "2026-06-05T00:00:00Z",
                        "text": "Chart",
                        "attachments": {"media_keys": ["3_abc"]},
                    }
                ],
                {"user-1": {"username": "source"}},
                {"3_abc": {"media_key": "3_abc", "type": "photo", "width": 100, "height": 100}},
                {"3_abc": str(media_file)},
                0,
                presentation,
                "source",
                "user-1",
            )

            html = page.read_text(encoding="utf-8")

        self.assertIn("Image AI description", html)
        self.assertIn("Visible chart for Tesla.", html)
        self.assertIn("TSLA", html)


if __name__ == "__main__":
    unittest.main()
