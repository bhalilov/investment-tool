import unittest

from investment_tool.analysis.openai import extract_response_text


class AnalysisOpenAITests(unittest.TestCase):
    def test_extract_response_text_prefers_output_text(self):
        self.assertEqual(extract_response_text({"output_text": "ready"}), "ready")

    def test_extract_response_text_collects_nested_output_chunks(self):
        response = {
            "output": [
                {"content": [{"type": "output_text", "text": "one"}]},
                {"content": [{"type": "text", "text": "two"}]},
            ]
        }

        self.assertEqual(extract_response_text(response), "one\ntwo")


if __name__ == "__main__":
    unittest.main()
