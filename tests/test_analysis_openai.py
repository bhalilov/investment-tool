import unittest
from unittest.mock import patch

from investment_tool.analysis.openai import call_responses_json, extract_response_text


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

    def test_call_responses_json_forwards_configured_api_base(self):
        with patch("investment_tool.analysis.openai.request_json") as request:
            request.return_value = {
                "id": "resp_1",
                "output_text": '{"ok": true}',
                "usage": {"input_tokens": 1, "output_tokens": 2},
            }

            parsed, _ = call_responses_json(
                api_key="key",
                model="model",
                system_prompt="system",
                user_content=[{"type": "input_text", "text": "hello"}],
                schema_name="schema",
                schema={"type": "object", "additionalProperties": False, "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                max_output_tokens=100,
                api_base="https://provider.example/v1",
            )

        self.assertTrue(parsed["ok"])
        self.assertEqual(request.call_args.kwargs["api_base"], "https://provider.example/v1")


if __name__ == "__main__":
    unittest.main()
