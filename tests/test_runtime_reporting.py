import unittest
from unittest.mock import patch

from investment_tool.runtime.reporting import JobReporter, format_report_line


class RuntimeReportingTests(unittest.TestCase):
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

    def test_checkpoint_stats_allows_processed_inside_stats(self):
        reporter = JobReporter("prices", total=3, every_items=1, every_seconds=0)

        with patch("builtins.print") as printed:
            reporter.checkpoint_stats({"processed": 1, "rows_written": 10}, processed=1, force=True)

        line = printed.call_args.args[0]
        self.assertIn("processed=1", line)
        self.assertIn("rows_written=10", line)


if __name__ == "__main__":
    unittest.main()
