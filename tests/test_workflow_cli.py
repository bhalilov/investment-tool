import contextlib
import io
import os
import tempfile
import unittest

from investment_tool.cli import main as cli_main


class WorkflowCliTests(unittest.TestCase):
    def call_cli(self, args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli_main.main(args)
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_workflow_help_lists_approved_commands(self):
        code, stdout, _ = self.call_cli(["workflow", "--help"])

        self.assertEqual(code, 0)
        self.assertIn("update", stdout)
        self.assertIn("rebuild", stdout)
        self.assertIn("doctor", stdout)

    def test_workflow_update_dry_run_reports_locked_stage_order(self):
        code, stdout, _ = self.call_cli(["workflow", "update", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertIn("DRY_RUN=true", stdout)
        self.assertIn("STAGES=x-capture,screenshots,prices,descriptions,render", stdout)

    def test_non_workflow_command_is_rejected(self):
        code, stdout, stderr = self.call_cli(["storage", "--help"])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Use: investment-tool workflow", stderr)

    def test_workflow_rebuild_requires_stage_or_all(self):
        code, _, stderr = self.call_cli(["workflow", "rebuild"])

        self.assertEqual(code, 2)
        self.assertIn("requires one or more --stage values or --all", stderr)

    def test_workflow_rebuild_all_excludes_explicit_repairs(self):
        code, stdout, _ = self.call_cli(["workflow", "rebuild", "--all", "--dry-run"])

        self.assertEqual(code, 0)
        self.assertIn("STAGES=x-raw,screenshots,prices,descriptions,render,articles", stdout)
        self.assertNotIn("x-repair-media-paths", stdout)
        self.assertNotIn("x-recover-media", stdout)

    def test_workflow_rebuild_accepts_explicit_x_maintenance_stages(self):
        code, stdout, _ = self.call_cli(
            [
                "workflow",
                "rebuild",
                "--stage",
                "x-reindex",
                "--stage",
                "x-repair-media-paths",
                "--stage",
                "x-recover-media",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertIn("STAGES=x-reindex,x-repair-media-paths,x-recover-media", stdout)

    def test_workflow_check_is_read_only_and_uses_runtime_root(self):
        old_data_root = os.environ.get("INVESTMENT_TOOL_DATA_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["INVESTMENT_TOOL_DATA_DIR"] = tmp
            try:
                code, stdout, _ = self.call_cli(["workflow", "check"])
            finally:
                if old_data_root is None:
                    os.environ.pop("INVESTMENT_TOOL_DATA_DIR", None)
                else:
                    os.environ["INVESTMENT_TOOL_DATA_DIR"] = old_data_root

        self.assertEqual(code, 0)
        self.assertIn("DATA_ROOT path=<data>", stdout)
        self.assertIn("MISSING_PATHS=", stdout)


if __name__ == "__main__":
    unittest.main()
