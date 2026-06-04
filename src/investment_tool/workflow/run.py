"""Top-level pipeline and maintenance orchestrator."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from investment_tool.runtime.reporting import start_reporter
from investment_tool.runtime.env import load_env
from investment_tool.sources.x.jobs import main as main_x_job, run_x_action


UPDATE_STAGE_ORDER = ("x-capture", "screenshots", "prices", "descriptions", "render")
REBUILD_STAGE_ORDER = ("x-raw", "screenshots", "prices", "descriptions", "render", "articles")
ALL_STAGE_NAMES = tuple(dict.fromkeys((*UPDATE_STAGE_ORDER, *REBUILD_STAGE_ORDER)))
SCREENSHOT_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_LOCK_STALE_SECONDS = 6 * 60 * 60


@dataclass
class StageResult:
    name: str
    status: str
    exit_code: int
    note: str = ""
    started_at: str = ""
    finished_at: str = ""

    def log_lines(self) -> list[str]:
        lines = [f"STAGE {self.name}", f"status: {self.status}", f"exit_code: {self.exit_code}"]
        if self.started_at:
            lines.append(f"started_at: {self.started_at}")
        if self.finished_at:
            lines.append(f"finished_at: {self.finished_at}")
        if self.note:
            lines.extend(["notes:", f"- {self.note}"])
        return lines


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def runtime_data_root() -> Path:
    configured = os.environ.get("INVESTMENT_TOOL_DATA_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path("~/investment-tool-data").expanduser()


def workflow_root() -> Path:
    return runtime_data_root() / "pipeline"


def acquire_workflow_lock(lock_path: Path, stale_seconds: int = DEFAULT_LOCK_STALE_SECONDS) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age < stale_seconds:
            raise RuntimeError(f"Workflow lock exists and is not stale: {lock_path}")
        lock_path.unlink()
    lock_path.write_text(
        "\n".join(
            [
                "workflow_lock",
                f"pid: {os.getpid()}",
                f"created_at: {iso_now()}",
                f"stale_after_seconds: {stale_seconds}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def release_workflow_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


def write_workflow_log(
    run_id: str,
    command: str,
    stages: Sequence[str],
    results: Sequence[StageResult],
    status: str,
) -> Path:
    logs_dir = workflow_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{run_id}__{command.replace(' ', '-')}.log"
    lines = [
        "# Investment Tool Workflow Run",
        "",
        "RUN",
        f"id: {run_id}",
        f"command: {command}",
        f"started_at: {results[0].started_at if results else iso_now()}",
        f"stages: {', '.join(stages)}",
        "",
    ]
    for result in results:
        lines.extend(result.log_lines())
        lines.append("")
    lines.extend(["DONE", f"status: {status}", f"finished_at: {iso_now()}", ""])
    payload = "\n".join(lines)
    log_path.write_text(payload, encoding="utf-8")
    (logs_dir / "latest.log").write_text(payload, encoding="utf-8")
    return log_path


def add_workflow_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-config", default="config/sources/x_accounts.json")
    parser.add_argument("--source-id", default="")


def add_workflow_x_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeline-pages", type=int, default=3)
    parser.add_argument("--conversation-pages", type=int, default=0)
    parser.add_argument("--max-threads", type=int, default=20)
    parser.add_argument("--conversation-id", default="")


def add_workflow_run_args(parser: argparse.ArgumentParser, stages: Sequence[str]) -> None:
    parser.add_argument("--stage", action="append", default=[], choices=stages, help="Run only this stage; repeatable.")
    parser.add_argument("--dry-run", action="store_true", help="Plan and report without API calls or data writes.")
    parser.add_argument("--force", action="store_true", help="Run selected stages even when local outputs already exist.")
    parser.add_argument("--max-runtime-minutes", type=int, default=0, help="Stop starting new stages after this many minutes.")
    add_workflow_source_args(parser)
    add_workflow_x_args(parser)


def build_workflow_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate investment-tool workflow stages.")
    subparsers = parser.add_subparsers(dest="command")

    for command in ("update", "sync", "refresh"):
        update = subparsers.add_parser(command, help="Run the scheduled incremental workflow.")
        add_workflow_run_args(update, UPDATE_STAGE_ORDER)
        update.add_argument("--skip", action="append", default=[], choices=UPDATE_STAGE_ORDER, help="Skip this stage; repeatable.")

    rebuild = subparsers.add_parser("rebuild", help="Run explicit historical or missing-data rebuild stages.")
    add_workflow_run_args(rebuild, REBUILD_STAGE_ORDER)
    rebuild.add_argument("--all", action="store_true", help="Run all rebuild stages.")
    rebuild.add_argument("--skip", action="append", default=[], choices=REBUILD_STAGE_ORDER, help="Skip this stage; repeatable.")
    rebuild.add_argument("--rebuild-staging-dir", default="")
    rebuild.add_argument("--replace-generated-json", action="store_true")

    for command in ("check", "doctor"):
        check = subparsers.add_parser(command, help="Run read-only workflow health checks.")
        add_workflow_source_args(check)

    return parser


def selected_stages(args: argparse.Namespace) -> list[str]:
    if args.command in {"update", "sync", "refresh"}:
        stages = list(args.stage or UPDATE_STAGE_ORDER)
    elif args.command == "rebuild":
        if args.all:
            stages = list(REBUILD_STAGE_ORDER)
        else:
            stages = list(args.stage or [])
    else:
        return []
    skipped = set(getattr(args, "skip", []) or [])
    return [stage for stage in stages if stage not in skipped]


def workflow_x_namespace(args: argparse.Namespace, **extra: object) -> argparse.Namespace:
    values = {
        "source_config": getattr(args, "source_config", "config/sources/x_accounts.json"),
        "source_id": getattr(args, "source_id", ""),
        "timeline_pages": getattr(args, "timeline_pages", 3),
        "conversation_pages": getattr(args, "conversation_pages", 0),
        "max_threads": getattr(args, "max_threads", 20),
        "conversation_id": getattr(args, "conversation_id", ""),
        "force": getattr(args, "force", False),
        "rebuild_staging_dir": getattr(args, "rebuild_staging_dir", ""),
        "replace_generated_json": getattr(args, "replace_generated_json", False),
    }
    values.update(extra)
    return argparse.Namespace(**values)


def screenshot_inbox_paths() -> list[Path]:
    inbox = runtime_data_root() / "manual_threads" / "inbox"
    if not inbox.exists():
        return []
    return sorted(path for path in inbox.iterdir() if path.is_file() and path.suffix.lower() in SCREENSHOT_SUFFIXES)


def run_screenshots_stage(args: argparse.Namespace) -> int:
    from investment_tool.sources.screenshots import bundles as screenshot_bundles

    paths = screenshot_inbox_paths()
    if not paths:
        print(f"SCREENSHOTS_INBOX={runtime_data_root() / 'manual_threads' / 'inbox'}")
        print("SCREENSHOTS_FOUND=0")
        return 0
    argv = [str(path) for path in paths]
    argv.extend(
        [
            "--output-dir",
            str(runtime_data_root() / "manual_threads"),
            "--source-config",
            getattr(args, "source_config", "config/sources/x_accounts.json"),
            "--source-id",
            getattr(args, "source_id", ""),
            "--analyze",
        ]
    )
    if getattr(args, "force", False):
        argv.append("--force")
    return screenshot_bundles.main(argv)


def run_stage(stage: str, args: argparse.Namespace) -> StageResult:
    started = iso_now()
    if getattr(args, "dry_run", False):
        return StageResult(stage, "planned", 0, "dry run only; stage was not executed", started, iso_now())
    try:
        if stage == "x-capture":
            code = run_x_action(workflow_x_namespace(args), "x-capture")
        elif stage == "x-raw":
            code = run_x_action(workflow_x_namespace(args), "x-raw-rebuild")
        elif stage == "render":
            code = run_x_action(workflow_x_namespace(args), "x-rerender")
        elif stage == "prices":
            from investment_tool.context import prices

            code = prices.main([])
        elif stage == "descriptions":
            from investment_tool.context import descriptions

            description_args = [
                "--source-config",
                getattr(args, "source_config", "config/sources/x_accounts.json"),
                "--source-id",
                getattr(args, "source_id", ""),
            ]
            if getattr(args, "force", False):
                description_args.append("--force")
            code = descriptions.main(description_args)
        elif stage == "screenshots":
            code = run_screenshots_stage(args)
        elif stage == "articles":
            from investment_tool.sources.articles import ingest as articles_ingest

            article_args = [
                "--source-config",
                getattr(args, "source_config", "config/sources/x_accounts.json"),
                "--source-id",
                getattr(args, "source_id", ""),
            ]
            if getattr(args, "force", False):
                article_args.append("--force-ai")
            code = articles_ingest.main(article_args)
        else:
            return StageResult(stage, "failed", 2, f"unknown stage: {stage}", started, iso_now())
        return StageResult(stage, "success" if code == 0 else "failed", code, "", started, iso_now())
    except Exception as exc:
        return StageResult(stage, "failed", 1, str(exc), started, iso_now())


def run_workflow_check(command: str) -> int:
    root = runtime_data_root()
    checks = {
        "data_root": root,
        "x_thread_json": root / "x_threads" / "thread_json",
        "x_raw_api": root / "x_threads" / "raw_api",
        "x_media": root / "x_threads" / "media",
        "media_analysis": root / "x_threads" / "media_analysis",
        "manual_inbox": root / "manual_threads" / "inbox",
        "market_prices": root / "market_prices",
        "workflow_logs": root / "pipeline" / "logs",
        "workflow_locks": root / "pipeline" / "locks",
    }
    print(f"WORKFLOW_CHECK={command}")
    missing = 0
    for name, path in checks.items():
        exists = path.exists()
        count = len(list(path.iterdir())) if exists and path.is_dir() else 0
        print(f"{name.upper()} path={path} exists={str(exists).lower()} items={count}")
        if name != "data_root" and not exists:
            missing += 1
    print(f"MISSING_PATHS={missing}")
    return 0


def should_skip_stage_due_to_failure(stage: str, results: Sequence[StageResult]) -> str | None:
    if stage != "render":
        return None
    failed_inputs = [result.name for result in results if result.status == "failed" and result.name in {"x-capture", "x-raw"}]
    if failed_inputs:
        return f"render skipped because input stage failed: {', '.join(failed_inputs)}"
    return None


def run_workflow(argv: Sequence[str] | None = None) -> int:
    load_env(Path.cwd() / ".env")
    parser = build_workflow_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command in {"check", "doctor"}:
        return run_workflow_check(args.command)
    if args.command == "rebuild" and not args.all and not args.stage:
        print("workflow rebuild requires one or more --stage values or --all.", file=sys.stderr)
        return 2

    stages = selected_stages(args)
    if not stages:
        print("No workflow stages selected.")
        return 0

    command_text = f"workflow {args.command}"
    if args.dry_run:
        print(f"WORKFLOW={args.command}")
        print(f"DRY_RUN=true")
        print(f"STAGES={','.join(stages)}")
        return 0

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    lock_path = workflow_root() / "locks" / f"workflow-{args.command}.lock"
    acquire_workflow_lock(lock_path)
    reporter = start_reporter("workflow", total=len(stages), mode=args.command, stages=",".join(stages))
    results: list[StageResult] = []
    started_monotonic = time.monotonic()
    try:
        for index, stage in enumerate(stages, start=1):
            if args.max_runtime_minutes and (time.monotonic() - started_monotonic) > args.max_runtime_minutes * 60:
                result = StageResult(stage, "skipped", 0, "max runtime reached before starting stage", iso_now(), iso_now())
            else:
                skip_note = should_skip_stage_due_to_failure(stage, results)
                if skip_note:
                    result = StageResult(stage, "skipped", 0, skip_note, iso_now(), iso_now())
                else:
                    result = run_stage(stage, args)
            results.append(result)
            reporter.checkpoint(processed=index, force=True, stage=stage, stage_status=result.status, exit_code=result.exit_code)
        failed = [result for result in results if result.status == "failed"]
        status = "failed" if failed else "success"
        log_path = write_workflow_log(run_id, command_text, stages, results, status)
        reporter.done(status=status, log=log_path)
        print(f"WORKFLOW_LOG={log_path}")
        return 1 if failed else 0
    finally:
        release_workflow_lock(lock_path)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "workflow":
        return run_workflow(argv[1:])
    return main_x_job(argv)


if __name__ == "__main__":
    raise SystemExit(main())
