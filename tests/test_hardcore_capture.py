import tempfile
import unittest
from pathlib import Path

from investment_tool import hardcore_capture


class HardcoreCaptureTests(unittest.TestCase):
    def test_parse_article_date_accepts_archive_formats(self):
        self.assertEqual(hardcore_capture.parse_article_date("25 May 2026"), "2026-05-25")
        self.assertEqual(hardcore_capture.parse_article_date("May 25, 2026"), "2026-05-25")

    def test_article_id_is_stable_and_filesystem_safe(self):
        item = {"index": 16, "title": "Infineon Technologies AG (IFX.DE, IFNNY)"}
        self.assertEqual(
            hardcore_capture.article_id(item),
            "016__infineon-technologies-ag-ifx.de-ifnny",
        )

    def test_extract_html_text_skips_scripts_and_collects_image_alt_text(self):
        html = """<!doctype html>
        <html>
          <head>
            <title>AJ Article</title>
            <style>.hidden{display:none}</style>
            <script>bad()</script>
          </head>
          <body>
            <div class="print-source">Saved from AJ Investment Research on 5/25/2026<br>
            https://aj-investment-research.ghost.io/example/</div>
            <article>
              <h1>TSLA Update</h1>
              <p>Tesla remains a positioning question.</p>
              <img alt="TSLA valuation corridor chart">
            </article>
          </body>
        </html>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "article.html"
            path.write_text(html, encoding="utf-8")
            text, meta = hardcore_capture.extract_html_text(path)

        self.assertEqual(meta["html_title"], "AJ Article")
        self.assertIn("TSLA Update", text)
        self.assertIn("Tesla remains a positioning question.", text)
        self.assertNotIn("bad()", text)
        self.assertNotIn("display:none", text)
        self.assertIn("TSLA valuation corridor chart", meta["image_alt_texts"])

    def test_markdown_marks_hardcore_articles_as_no_ocr(self):
        record = {
            "article_id": "001__example",
            "index": 1,
            "title": "Example",
            "date_iso": "2026-05-25",
            "url": "https://aj-investment-research.ghost.io/example/",
            "html_path": "/tmp/example.html",
            "pdf_path": "/tmp/example.pdf",
            "text": "Article body",
            "analysis": {
                "readable_title": "TSLA - Example",
                "primary_ticker": "TSLA",
                "context_tickers": [],
                "mentioned_only_tickers": [],
                "summary": "Short summary.",
                "signal": "THESIS_UPDATE",
                "stance": "MIXED",
                "time_horizon": "MONTHS",
                "priority": "P2",
            },
        }

        markdown = hardcore_capture.render_markdown(record)

        self.assertIn("Feed Type: article", markdown)
        self.assertIn("OCR Used: false", markdown)
        self.assertIn("## Extracted Article Text", markdown)


if __name__ == "__main__":
    unittest.main()
