import argparse
import contextlib
import io
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_tool.cli import main as cli_main
from investment_tool.runtime.config import WorkflowStage
from investment_tool.workflow import run as workflow_run


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

    def test_run_stage_uses_registry_backed_stage_runner(self):
        seen = []

        def fake_module_main(stage, _args):
            seen.append((stage.stage, stage.entrypoint))
            return 0

        args = argparse.Namespace(dry_run=False)
        with patch.dict(workflow_run.STAGE_RUNNERS, {"module_main": fake_module_main}):
            result = workflow_run.run_stage("prices", args)

        self.assertEqual(result.status, "success")
        self.assertEqual(seen, [("prices", "investment_tool.context.prices")])

    def test_workflow_update_passes_incremental_to_prices(self):
        stage = WorkflowStage(
            stage="prices",
            module_id="prices",
            platform="market_data",
            kind="context_data",
            entrypoint="investment_tool.context.prices",
            feed_config="",
            runner="module_main",
            action="",
            argv=(),
        )

        argv = workflow_run.resolve_stage_argv(stage, argparse.Namespace(command="update", force=False))

        self.assertIn("--incremental", argv)

    def test_workflow_rebuild_does_not_pass_incremental_to_prices(self):
        stage = WorkflowStage(
            stage="prices",
            module_id="prices",
            platform="market_data",
            kind="context_data",
            entrypoint="investment_tool.context.prices",
            feed_config="",
            runner="module_main",
            action="",
            argv=(),
        )

        argv = workflow_run.resolve_stage_argv(stage, argparse.Namespace(command="rebuild", force=False))

        self.assertNotIn("--incremental", argv)

    def test_update_descriptions_scope_uses_latest_x_capture_media_keys(self):
        old_data_root = os.environ.get("INVESTMENT_TOOL_DATA_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["INVESTMENT_TOOL_DATA_DIR"] = tmp
            usage = Path(tmp) / "feeds" / "x" / "usage"
            usage.mkdir(parents=True)
            (usage / "latest_capture_manifest.json").write_text(
                json.dumps({"description_media_keys": ["3_b", "3_a", "3_a"]}),
                encoding="utf-8",
            )
            stage = WorkflowStage(
                stage="descriptions",
                module_id="descriptions",
                platform="local",
                kind="context",
                entrypoint="investment_tool.context.descriptions",
                feed_config="config/feeds/x_accounts.json",
                runner="descriptions",
                action="",
                argv=(),
            )
            args = argparse.Namespace(command="update", feed_config="", feed_id="", force=False)
            calls = []
            stdout = io.StringIO()
            try:
                with patch("investment_tool.context.descriptions.main", side_effect=lambda argv: calls.append(argv) or 0):
                    with contextlib.redirect_stdout(stdout):
                        code = workflow_run.run_descriptions_stage(stage, args)
            finally:
                if old_data_root is None:
                    os.environ.pop("INVESTMENT_TOOL_DATA_DIR", None)
                else:
                    os.environ["INVESTMENT_TOOL_DATA_DIR"] = old_data_root

        self.assertEqual(code, 0)
        self.assertIn("DESCRIPTIONS_SCOPE=latest_x_capture", stdout.getvalue())
        self.assertEqual(calls[0].count("--media-key"), 2)
        self.assertLess(calls[0].index("3_a"), calls[0].index("3_b"))

    def test_update_descriptions_skips_when_latest_capture_has_no_media(self):
        old_data_root = os.environ.get("INVESTMENT_TOOL_DATA_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["INVESTMENT_TOOL_DATA_DIR"] = tmp
            stage = WorkflowStage(
                stage="descriptions",
                module_id="descriptions",
                platform="local",
                kind="context",
                entrypoint="investment_tool.context.descriptions",
                feed_config="config/feeds/x_accounts.json",
                runner="descriptions",
                action="",
                argv=(),
            )
            args = argparse.Namespace(command="update", feed_config="", feed_id="", force=False)
            stdout = io.StringIO()
            try:
                with patch("investment_tool.context.descriptions.main") as mocked:
                    with contextlib.redirect_stdout(stdout):
                        code = workflow_run.run_descriptions_stage(stage, args)
            finally:
                if old_data_root is None:
                    os.environ.pop("INVESTMENT_TOOL_DATA_DIR", None)
                else:
                    os.environ["INVESTMENT_TOOL_DATA_DIR"] = old_data_root

        self.assertEqual(code, 0)
        self.assertFalse(mocked.called)
        self.assertIn("DESCRIPTIONS_SKIPPED=no_media_keys_from_latest_capture", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
