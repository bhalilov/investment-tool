"""X stage job wrappers used by workflow and legacy CLI entrypoints."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Sequence

from investment_tool.runtime.env import load_env
from investment_tool.runtime.paths import data_root_for_x_root, portable_path, resolve_portable_path
from investment_tool.runtime.reporting import start_reporter
from investment_tool.feeds.x.api import XClient, refresh_x_user_token
from investment_tool.feeds.x.capture import (
    XCaptureOptions,
    prepare_x_capture_paths,
    recover_missing_media_metadata,
    run_live_x_capture,
)
from investment_tool.feeds.x.context import XCaptureContext, load_x_capture_context
from investment_tool.feeds.x.rebuild import rebuild_from_raw_api
from investment_tool.feeds.x.store import (
    apply_cached_relevance_gate,
    entries_from_cached_json,
    load_owned_tickers,
    render_all_indexes,
    repair_cached_media_paths,
    rerender_cached_threads,
)


X_ACTIONS = {"x-capture", "x-reindex", "x-rerender", "x-raw-rebuild", "x-repair-media-paths", "x-recover-media"}


def apply_context_data_root(context: XCaptureContext) -> None:
    if context.profile.data_root and not os.environ.get("INVESTMENT_TOOL_DATA_DIR"):
        os.environ["INVESTMENT_TOOL_DATA_DIR"] = str(data_root_for_x_root(context.profile.data_root))


def add_x_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--feed-config", default="config/feeds/x_accounts.json")
    parser.add_argument("--feed-id", default="")
    parser.add_argument("--timeline-pages", type=int, default=3)
    parser.add_argument("--conversation-pages", type=int, default=0, help="Override configured conversation page depth.")
    parser.add_argument("--max-threads", type=int, default=20)
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--force", action="store_true", help="Re-fetch and overwrite already-cached threads")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run X capture stages and maintenance jobs.")
    subparsers = parser.add_subparsers(dest="action")

    capture = subparsers.add_parser("x-capture", help="Run the live X capture stage only. No AI or vector sync.")
    add_x_common_args(capture)

    reindex = subparsers.add_parser("x-reindex", help="Regenerate X indexes from cached JSON without X API calls.")
    add_x_common_args(reindex)

    rerender = subparsers.add_parser("x-rerender", help="Regenerate X thread HTML and indexes from cached JSON without X API calls.")
    add_x_common_args(rerender)

    raw = subparsers.add_parser("x-raw-rebuild", help="Rebuild X generated JSON from saved raw API responses.")
    add_x_common_args(raw)
    raw.add_argument("--rebuild-staging-dir", default="", help="Where to write staged rebuilt JSON records.")
    raw.add_argument(
        "--replace-generated-json",
        action="store_true",
        help="After staging, delete/replace generated thread JSON and ignored JSON. Raw API and media are never deleted.",
    )

    repair = subparsers.add_parser("x-repair-media-paths", help="Repair cached X thread JSON media path references.")
    add_x_common_args(repair)

    recover = subparsers.add_parser("x-recover-media", help="Use X API to recover missing media metadata and download photos only.")
    add_x_common_args(recover)

    return parser


def build_legacy_x_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture configured X feed threads into readable local HTML files.")
    add_x_common_args(parser)
    parser.add_argument("--reindex-only", action="store_true", help="Regenerate indexes from cached JSON without X API calls")
    parser.add_argument("--rerender-only", action="store_true", help="Regenerate thread HTML from cached JSON without X API calls")
    parser.add_argument(
        "--rebuild-from-raw-api",
        action="store_true",
        help="Rebuild generated thread JSON from saved raw API responses without calling X.",
    )
    parser.add_argument("--rebuild-staging-dir", default="", help="Where to write staged rebuilt JSON records.")
    parser.add_argument(
        "--replace-generated-json",
        action="store_true",
        help="After staging, delete/replace generated thread JSON and ignored JSON. Raw API and media are never deleted.",
    )
    parser.add_argument(
        "--recover-missing-media-metadata",
        action="store_true",
        help="Use X API to refetch tweets whose media keys lack raw media metadata; download recovered photos only.",
    )
    parser.add_argument(
        "--repair-media-paths",
        action="store_true",
        help="Repair cached thread JSON so media_paths only contains media referenced by that thread.",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Deprecated. X capture no longer runs AI; use the configured AI pass pipeline instead.",
    )
    parser.add_argument(
        "--no-analyze",
        action="store_true",
        help="Deprecated no-op kept for old command compatibility.",
    )
    return parser


def load_x_context_from_args(args: argparse.Namespace) -> XCaptureContext:
    context = load_x_capture_context(args.feed_config, args.feed_id)
    apply_context_data_root(context)
    if args.conversation_pages <= 0:
        args.conversation_pages = int(context.thread_rules.get("conversation_pages") or 5)
    return context


def x_mode_from_legacy_args(args: argparse.Namespace) -> str:
    if args.analyze:
        print("capture_threads no longer runs AI. Use the configured AI pass pipeline for thread analysis.", file=sys.stderr)
        return "invalid-analyze"
    if args.repair_media_paths:
        return "x-repair-media-paths"
    if args.rebuild_from_raw_api:
        return "x-raw-rebuild"
    if args.reindex_only:
        return "x-reindex"
    if args.rerender_only:
        return "x-rerender"
    if args.recover_missing_media_metadata:
        return "x-recover-media"
    return "x-capture"


def print_key_values(values: dict[str, object]) -> None:
    for key, value in values.items():
        print(f"{key.upper()}={value}")


def run_x_action(args: argparse.Namespace, action: str) -> int:
    if action == "invalid-analyze":
        return 2

    env_path = Path.cwd() / ".env"
    load_env(env_path)
    context = load_x_context_from_args(args)

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = prepare_x_capture_paths(run_id, context.profile.data_root)

    if action == "x-repair-media-paths":
        stats = repair_cached_media_paths(paths.json_dir, paths.root / "backups")
        print_key_values(stats)
        return 0 if int(stats["failed"]) == 0 else 1

    if action == "x-raw-rebuild":
        staging_dir = (
            resolve_portable_path(args.rebuild_staging_dir)
            if getattr(args, "rebuild_staging_dir", "")
            else paths.root / "rebuild" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        reporter = start_reporter(
            "x-capture",
            mode="raw_rebuild_replace" if getattr(args, "replace_generated_json", False) else "raw_rebuild_staging",
            raw_dir=portable_path(paths.root / "raw"),
            staging_dir=portable_path(staging_dir),
            replace_generated_json=getattr(args, "replace_generated_json", False),
        )
        manifest = rebuild_from_raw_api(paths.root, staging_dir, getattr(args, "replace_generated_json", False), context)
        reporter.done(**manifest)
        print_key_values(manifest)
        return 0 if int(manifest.get("failed_raw_files") or 0) == 0 else 1

    reporter = start_reporter(
        "x-capture",
        total=args.max_threads,
        every_items=10,
        every_seconds=30,
        mode={
            "x-recover-media": "recover_missing_media",
            "x-reindex": "reindex",
            "x-rerender": "rerender",
            "x-capture": "capture",
        }[action],
        timeline_pages=args.timeline_pages,
        conversation_pages=args.conversation_pages,
        max_threads=args.max_threads,
        conversation_id=args.conversation_id or "",
        ai_in_capture="false",
        ai_pipeline="separate_thread_passes",
        x_usage_available="usage_endpoint_when_supported",
        openai_usage_available="not_used_by_capture",
        raw_dir=portable_path(paths.raw_dir),
    )

    if action == "x-reindex":
        ignored = apply_cached_relevance_gate(paths.root, paths.json_dir, paths.threads_dir, context)
        entries = entries_from_cached_json(paths.json_dir, paths.threads_dir, context)
        render_all_indexes(paths.presentation_root, entries, load_owned_tickers())
        index_path = paths.presentation_root / "indexes" / "index.html"
        print(f"INDEX={portable_path(index_path)}")
        print("REINDEX_ONLY=true")
        print(f"THREADS={len(entries)}")
        print(f"IGNORED={ignored}")
        print("API_CALLS=0")
        reporter.done(mode="reindex", threads=len(entries), ignored=ignored, api_calls=0, index=portable_path(index_path))
        return 0

    if action == "x-rerender":
        ignored = apply_cached_relevance_gate(paths.root, paths.json_dir, paths.threads_dir, context)
        entries = rerender_cached_threads(
            paths.root,
            paths.json_dir,
            paths.threads_dir,
            args.conversation_id,
            context,
            paths.presentation_root,
        )
        render_all_indexes(paths.presentation_root, entries, load_owned_tickers())
        index_path = paths.presentation_root / "indexes" / "index.html"
        print(f"INDEX={portable_path(index_path)}")
        print("RERENDER_ONLY=true")
        print(f"THREADS={len(entries)}")
        print(f"IGNORED={ignored}")
        print("API_CALLS=0")
        reporter.done(mode="rerender", threads=len(entries), ignored=ignored, api_calls=0, index=portable_path(index_path))
        return 0

    token = os.environ.get("X_USER_ACCESS_TOKEN", "").strip()
    if not token:
        print("Missing X_USER_ACCESS_TOKEN in .env", file=sys.stderr)
        return 1

    if action == "x-recover-media":
        client = XClient(token, paths.raw_dir, refresh_callback=lambda: refresh_x_user_token(env_path))
        stats = recover_missing_media_metadata(paths.root, client, context)
        reporter.done(**stats, raw_dir=portable_path(paths.raw_dir))
        print_key_values(stats)
        return 0

    options = XCaptureOptions(
        timeline_pages=args.timeline_pages,
        conversation_pages=args.conversation_pages,
        max_threads=args.max_threads,
        conversation_id=args.conversation_id or "",
        force=args.force,
    )
    result = run_live_x_capture(paths, run_id, env_path, token, options, context, reporter)
    print(f"INDEX={result['index']}")
    print(f"THREADS={result['threads']}")
    print(f"RAW_API_DIR={result['raw_api_dir']}")
    print(f"MEDIA_DIR={result['media_dir']}")
    print(f"API_CALLS={result['api_calls']}")
    print(f"UNIQUE_POST_READS_ESTIMATE={result['unique_post_reads_estimate']}")
    print(f"ESTIMATED_X_COST_USD={result['estimated_x_cost_usd']}")
    print("AI_IN_CAPTURE=false")
    reporter.done(
        threads=result["threads"],
        ignored=result["ignored"],
        api_calls=result["api_calls"],
        unique_post_reads_estimate=result["unique_post_reads_estimate"],
        estimated_x_cost_usd=result["estimated_x_cost_usd"],
        ai_in_capture=False,
        index=result["index"],
    )
    return 0


def main_legacy_x_capture(argv: Sequence[str] | None = None) -> int:
    parser = build_legacy_x_parser()
    args = parser.parse_args(argv)
    return run_x_action(args, x_mode_from_legacy_args(args))


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] not in X_ACTIONS:
        return main_legacy_x_capture(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_x_action(args, args.action)


if __name__ == "__main__":
    raise SystemExit(main())
