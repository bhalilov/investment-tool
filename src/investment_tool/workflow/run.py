"""Top-level workflow and maintenance orchestrator.

This module coordinates stages only. Feed-specific implementation belongs in
feed/context/presentation modules and is called through narrow adapters.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from investment_tool.runtime.config import DEFAULT_X_MODULE_ID, WorkflowStage, default_feed_config, load_workflow_stages
from investment_tool.runtime.env import load_env
from investment_tool.runtime.paths import portable_path, storage_paths
from investment_tool.runtime.reporting import start_reporter
from investment_tool.feeds.x.jobs import run_x_action


# Keep stage order explicit and boring. Scheduled update and manual rebuild have
# different intent, so they get separate ordered lists instead of one clever DAG.
UPDATE_STAGE_ORDER = ("x-capture", "screenshots", "prices", "descriptions", "render")
REBUILD_ALL_STAGE_ORDER = ("x-raw", "screenshots", "prices", "descriptions", "render", "articles")
REBUILD_STAGE_CHOICES = (
    *REBUILD_ALL_STAGE_ORDER,
    "x-reindex",
    "x-repair-media-paths",
    "x-recover-media",
)
ALL_STAGE_NAMES = tuple(dict.fromkeys((*UPDATE_STAGE_ORDER, *REBUILD_STAGE_CHOICES)))
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


def workflow_root() -> Path:
    return storage_paths().workflow_root


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


def add_workflow_feed_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--feed-config", default=default_feed_config(DEFAULT_X_MODULE_ID))
    parser.add_argument("--feed-id", default="")


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
    add_workflow_feed_args(parser)
    add_workflow_x_args(parser)


def build_workflow_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate investment-tool workflow stages.")
    subparsers = parser.add_subparsers(dest="command")

    for command in ("update", "sync", "refresh"):
        update = subparsers.add_parser(command, help="Run the scheduled incremental workflow.")
        add_workflow_run_args(update, UPDATE_STAGE_ORDER)
        update.add_argument("--skip", action="append", default=[], choices=UPDATE_STAGE_ORDER, help="Skip this stage; repeatable.")

    rebuild = subparsers.add_parser("rebuild", help="Run explicit historical or missing-data rebuild stages.")
    add_workflow_run_args(rebuild, REBUILD_STAGE_CHOICES)
    rebuild.add_argument("--all", action="store_true", help="Run all rebuild stages.")
    rebuild.add_argument("--skip", action="append", default=[], choices=REBUILD_STAGE_CHOICES, help="Skip this stage; repeatable.")
    rebuild.add_argument("--rebuild-staging-dir", default="")
    rebuild.add_argument("--replace-generated-json", action="store_true")

    for command in ("check", "doctor"):
        check = subparsers.add_parser(command, help="Run read-only workflow health checks.")
        add_workflow_feed_args(check)

    return parser


def selected_stages(args: argparse.Namespace) -> list[str]:
    if args.command in {"update", "sync", "refresh"}:
        stages = list(args.stage or UPDATE_STAGE_ORDER)
    elif args.command == "rebuild":
        if args.all:
            stages = list(REBUILD_ALL_STAGE_ORDER)
        else:
            stages = list(args.stage or [])
    else:
        return []
    skipped = set(getattr(args, "skip", []) or [])
    return [stage for stage in stages if stage not in skipped]


def workflow_x_namespace(args: argparse.Namespace, feed_config_default: str = "", **extra: object) -> argparse.Namespace:
    values = {
        "feed_config": getattr(args, "feed_config", "") or feed_config_default or default_feed_config(DEFAULT_X_MODULE_ID),
        "feed_id": getattr(args, "feed_id", ""),
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
    inbox = storage_paths().screenshots_inbox
    if not inbox.exists():
        return []
    return sorted(path for path in inbox.iterdir() if path.is_file() and path.suffix.lower() in SCREENSHOT_SUFFIXES)


def run_screenshots_stage(stage: WorkflowStage, args: argparse.Namespace) -> int:
    from investment_tool.feeds.screenshots import bundles as screenshot_bundles

    paths = screenshot_inbox_paths()
    if not paths:
        print(f"SCREENSHOTS_INBOX={portable_path(storage_paths().screenshots_inbox)}")
        print("SCREENSHOTS_FOUND=0")
        return 0
    argv = [str(path) for path in paths]
    argv.extend(
        [
            "--output-dir",
            portable_path(storage_paths().screenshots_root),
            "--feed-config",
            getattr(args, "feed_config", "") or stage.feed_config or default_feed_config(DEFAULT_X_MODULE_ID),
            "--feed-id",
            getattr(args, "feed_id", ""),
            "--analyze",
        ]
    )
    if getattr(args, "force", False):
        argv.append("--force")
    return screenshot_bundles.main(argv)


def resolve_stage_argv(stage: WorkflowStage, args: argparse.Namespace) -> list[str]:
    argv = [item.replace("{feed_config}", stage.feed_config) for item in stage.argv]
    if stage.stage == "prices" and getattr(args, "command", "") in {"update", "sync", "refresh"} and not getattr(args, "force", False):
        argv.append("--incremental")
    return argv


def run_module_main_stage(stage: WorkflowStage, args: argparse.Namespace) -> int:
    module = importlib.import_module(stage.entrypoint)
    return int(module.main(resolve_stage_argv(stage, args)))


def run_x_action_stage(stage: WorkflowStage, args: argparse.Namespace) -> int:
    return run_x_action(workflow_x_namespace(args, stage.feed_config), stage.action)


def run_descriptions_stage(stage: WorkflowStage, args: argparse.Namespace) -> int:
    from investment_tool.context import descriptions

    description_args = [
        "--feed-config",
        getattr(args, "feed_config", "") or stage.feed_config or default_feed_config(DEFAULT_X_MODULE_ID),
        "--feed-id",
        getattr(args, "feed_id", ""),
    ]
    if getattr(args, "force", False):
        description_args.append("--force")
    if getattr(args, "command", "") in {"update", "sync", "refresh"}:
        media_keys = latest_x_capture_media_keys()
        print("DESCRIPTIONS_SCOPE=latest_x_capture")
        print(f"DESCRIPTIONS_MEDIA_KEYS={len(media_keys)}")
        if not media_keys:
            print("DESCRIPTIONS_SKIPPED=no_media_keys_from_latest_capture")
            return 0
        for key in media_keys:
            description_args.extend(["--media-key", key])
    return descriptions.main(description_args)


STAGE_RUNNERS = {
    "module_main": run_module_main_stage,
    "x_action": run_x_action_stage,
    "screenshots_inbox": run_screenshots_stage,
    "descriptions": run_descriptions_stage,
}


def latest_x_capture_media_keys() -> list[str]:
    manifest_path = storage_paths().x_usage / "latest_capture_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    keys = data.get("description_media_keys") or []
    if not isinstance(keys, list):
        return []
    return sorted({str(key).strip() for key in keys if str(key).strip()})


def run_stage(stage_name: str, args: argparse.Namespace) -> StageResult:
    started = iso_now()
    if getattr(args, "dry_run", False):
        return StageResult(stage_name, "planned", 0, "dry run only; stage was not executed", started, iso_now())
    try:
        stage = load_workflow_stages().get(stage_name)
        if not stage:
            return StageResult(stage_name, "failed", 2, f"unknown stage: {stage_name}", started, iso_now())
        runner = STAGE_RUNNERS.get(stage.runner)
        if not runner:
            return StageResult(stage_name, "failed", 2, f"unknown stage runner: {stage.runner}", started, iso_now())
        code = runner(stage, args)
        return StageResult(stage_name, "success" if code == 0 else "failed", code, "", started, iso_now())
    except Exception as exc:
        return StageResult(stage_name, "failed", 1, str(exc), started, iso_now())


def run_workflow_check(command: str) -> int:
    from investment_tool.feeds.x.verify import verify_x_records

    paths = storage_paths()
    root = paths.root
    checks = {
        "data_root": root,
        "x_records": paths.x_records,
        "x_raw": paths.x_raw,
        "x_media": paths.x_media,
        "x_descriptions": paths.x_descriptions,
        "screenshots_inbox": paths.screenshots_inbox,
        "prices": paths.prices_root,
        "presentation_indexes": paths.indexes,
        "workflow_logs": paths.workflow_logs,
        "workflow_locks": paths.workflow_locks,
    }
    legacy_checks = {
        "legacy_x_threads": root / "x_threads",
        "legacy_manual_threads": root / "manual_threads",
        "legacy_market_prices": root / "market_prices",
        "legacy_hardcore": root / "hardcore",
        "legacy_pipeline": root / "pipeline",
    }
    print(f"WORKFLOW_CHECK={command}")
    missing = 0
    for name, path in checks.items():
        exists = path.exists()
        count = len(list(path.iterdir())) if exists and path.is_dir() else 0
        print(f"{name.upper()} path={portable_path(path)} exists={str(exists).lower()} items={count}")
        if name != "data_root" and not exists:
            missing += 1
    legacy_present = 0
    for name, path in legacy_checks.items():
        exists = path.exists()
        count = len(list(path.iterdir())) if exists and path.is_dir() else 0
        if exists:
            legacy_present += 1
        print(f"{name.upper()} path={portable_path(path)} exists={str(exists).lower()} items={count}")
    x_verify = verify_x_records(paths.x_records)
    print(
        f"X_RECORD_VERIFY records={x_verify['records']} invalid_json={x_verify['invalid_json']} "
        f"violations={x_verify['violation_count']} warnings={x_verify['warning_count']}"
    )
    for violation in x_verify["violations"][:20]:
        print(f"X_RECORD_VIOLATION {json_like(violation)}")
    for warning in x_verify["warnings"][:20]:
        print(f"X_RECORD_WARNING {json_like(warning)}")
    print(f"MISSING_PATHS={missing}")
    print(f"LEGACY_PATHS_PRESENT={legacy_present}")
    return 1 if x_verify["violation_count"] else 0


def json_like(value: dict[str, Any]) -> str:
    return " ".join(f"{key}={value[key]}" for key in sorted(value))


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
        reporter.done(status=status, log=portable_path(log_path))
        print(f"WORKFLOW_LOG={portable_path(log_path)}")
        return 1 if failed else 0
    finally:
        release_workflow_lock(lock_path)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "workflow":
        return run_workflow(argv[1:])
    return run_workflow(argv)


if __name__ == "__main__":
    raise SystemExit(main())
