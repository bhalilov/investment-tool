import unittest

from investment_tool.runtime.reporting import format_report_line


class ReportingTests(unittest.TestCase):
    def test_vibe_is_bracket_prefix_not_payload_field(self):
        line = format_report_line(
            "CHECKPOINT",
            {
                "vibe": "lees-stirring",
                "job": "hardcore_capture",
                "processed": 12,
                "total": 93,
            },
        )

        self.assertTrue(line.startswith("[LEES-STIRRING] CHECKPOINT "))
        self.assertIn("job=hardcore_capture", line)
        self.assertIn("processed=12", line)
        self.assertNotIn("vibe=", line)


if __name__ == "__main__":
    unittest.main()
