#!/usr/bin/env python3
"""Import and reconstruct X threads captured as manual screenshots."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from investment_tool.context.descriptions import image_data_url
from investment_tool.analysis.openai import call_responses_json
from investment_tool.runtime.reporting import estimate_openai_cost_usd, start_reporter
from investment_tool.runtime.env import load_env
from investment_tool.runtime.config import SourceProfile, load_x_source_profile, source_identity, source_label


DEFAULT_DATA_DIR = Path("~/investment-tool-data").expanduser()
DEFAULT_OUTPUT_DIR = DEFAULT_DATA_DIR / "manual_threads"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SOURCE_PROFILE: SourceProfile = load_x_source_profile()


def configure_source(profile: SourceProfile) -> None:
    global SOURCE_PROFILE
    SOURCE_PROFILE = profile


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned.lower() or "manual-screenshots"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_id_for(paths: list[Path], bundle_name: str = "") -> str:
    if bundle_name:
        return slugify(bundle_name)
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path).encode("utf-8"))
        if path.exists():
            digest.update(file_sha256(path).encode("ascii"))
    return f"manual-{digest.hexdigest()[:12]}"


def bundle_path(output_dir: Path, bundle_id: str) -> Path:
    return output_dir / "bundles" / f"{bundle_id}.json"


def imported_media_dir(output_dir: Path, bundle_id: str) -> Path:
    return output_dir / "media" / bundle_id


def normalize_sources(paths: list[str], source_flags: list[str]) -> list[Path]:
    combined = [*source_flags, *paths]
    normalized = [Path(raw).expanduser() for raw in combined if raw.strip()]
    if not normalized:
        raise ValueError("No screenshot paths were provided.")
    for path in normalized:
        if not path.exists():
            raise FileNotFoundError(f"Screenshot does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Screenshot path is not a file: {path}")
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported screenshot type: {path}")
    return normalized


def image_size(path: Path) -> tuple[int | None, int | None]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data.startswith(b"\xff\xd8"):
        idx = 2
        while idx + 9 < len(data):
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            idx += 2
            while marker == 0xFF and idx < len(data):
                marker = data[idx]
                idx += 1
            if marker in {0xD8, 0xD9}:
                continue
            if idx + 2 > len(data):
                break
            length = int.from_bytes(data[idx : idx + 2], "big")
            if length < 2:
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            } and idx + 7 < len(data):
                height = int.from_bytes(data[idx + 3 : idx + 5], "big")
                width = int.from_bytes(data[idx + 5 : idx + 7], "big")
                return width, height
            idx += length
    return None, None


def embedded_datetime(path: Path) -> str:
    match = re.search(rb"20\d\d:\d\d:\d\d \d\d:\d\d:\d\d", path.read_bytes()[:65536])
    if not match:
        return ""
    return match.group(0).decode("ascii", errors="ignore")


def destination_name(index: int, path: Path, digest: str) -> str:
    suffix = path.suffix.lower()
    return f"{index:03d}_{digest[:12]}{suffix}"


def screenshot_record(index: int, source_path: Path, dest_path: Path, digest: str) -> dict[str, Any]:
    width, height = image_size(source_path)
    return {
        "index": index,
        "source_path": str(source_path),
        "imported_path": str(dest_path),
        "original_filename": source_path.name,
        "mime_type": mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
        "file_size": source_path.stat().st_size,
        "file_sha256": digest,
        "width": width,
        "height": height,
        "embedded_datetime": embedded_datetime(source_path),
    }


def build_bundle_record(
    *,
    bundle_id: str,
    bundle_name: str,
    sources: list[Path],
    output_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    media_dir = imported_media_dir(output_dir, bundle_id)
    screenshots = []
    seen_hashes: dict[str, int] = {}
    for index, source in enumerate(sources, start=1):
        digest = file_sha256(source)
        dest = media_dir / destination_name(index, source, digest)
        record = screenshot_record(index, source, dest, digest)
        if digest in seen_hashes:
            record["duplicate_of_index"] = seen_hashes[digest]
        else:
            record["duplicate_of_index"] = None
            seen_hashes[digest] = index
        screenshots.append(record)
    return {
        "bundle_id": bundle_id,
        "bundle_name": bundle_name,
        "source_type": "manual_x_screenshot_bundle",
        "source": source_identity(SOURCE_PROFILE),
        "created_at": iso_now(),
        "analysis_stage": "imported_pending_reconstruction",
        "status": "dry_run" if dry_run else "imported",
        "screenshots": screenshots,
        "stitch_groups": [],
        "reconstructed_threads": [],
        "reconstruction": None,
        "notes": [
            "Manual screenshots are source records. AI reconstruction should group overlapping scroll captures before extracting threads.",
            "Screenshots embedded inside visible X posts should be recorded as embedded_media on the reconstructed post.",
        ],
    }


def write_bundle(record: dict[str, Any], sources: list[Path], output_dir: Path, force: bool) -> Path:
    path = bundle_path(output_dir, record["bundle_id"])
    media_dir = imported_media_dir(output_dir, record["bundle_id"])
    if path.exists() and not force:
        raise FileExistsError(f"Manual screenshot bundle already exists: {path}")
    media_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(sources) != len(record["screenshots"]):
        raise ValueError("Source count does not match screenshot record count.")
    for source, screenshot in zip(sources, record["screenshots"]):
        shutil.copy2(source, screenshot["imported_path"])
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def reconstruction_schema() -> dict[str, Any]:
    post_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "post_local_id": {"type": "string", "maxLength": 80},
            "author_name": {"type": "string", "maxLength": 120},
            "username": {"type": "string", "maxLength": 80},
            "is_source_account": {"type": "boolean"},
            "visible_time": {"type": "string", "maxLength": 80},
            "text": {"type": "string", "maxLength": 4000},
            "relation": {
                "type": "string",
                "enum": ["root", "reply", "quote", "nested_media_caption", "unknown"],
            },
            "parent_post_local_id": {"type": "string", "maxLength": 80},
            "screenshot_indexes": {"type": "array", "maxItems": 20, "items": {"type": "integer"}},
            "starts_cut_off": {"type": "boolean"},
            "ends_cut_off": {"type": "boolean"},
            "is_duplicate_merged": {"type": "boolean"},
            "visible_metrics": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "replies": {"type": "string", "maxLength": 40},
                    "reposts": {"type": "string", "maxLength": 40},
                    "likes": {"type": "string", "maxLength": 40},
                    "bookmarks": {"type": "string", "maxLength": 40},
                    "views": {"type": "string", "maxLength": 40},
                },
                "required": ["replies", "reposts", "likes", "bookmarks", "views"],
            },
            "embedded_media": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "media_local_id": {"type": "string", "maxLength": 80},
                        "screenshot_indexes": {"type": "array", "maxItems": 20, "items": {"type": "integer"}},
                        "media_type": {
                            "type": "string",
                            "enum": ["screenshot", "stock_chart", "photo", "video_preview", "article_card", "dashboard", "unknown"],
                        },
                        "summary": {"type": "string", "maxLength": 1200},
                        "visible_text": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 180}},
                        "detected_tickers": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 24}},
                        "uncertainties": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 180}},
                    },
                    "required": [
                        "media_local_id",
                        "screenshot_indexes",
                        "media_type",
                        "summary",
                        "visible_text",
                        "detected_tickers",
                        "uncertainties",
                    ],
                },
            },
        },
        "required": [
            "post_local_id",
            "author_name",
            "username",
            "is_source_account",
            "visible_time",
            "text",
            "relation",
            "parent_post_local_id",
            "screenshot_indexes",
            "starts_cut_off",
            "ends_cut_off",
            "is_duplicate_merged",
            "visible_metrics",
            "embedded_media",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "bundle_id": {"type": "string"},
            "stitch_groups": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "group_id": {"type": "string", "maxLength": 80},
                        "screenshot_indexes": {"type": "array", "maxItems": 20, "items": {"type": "integer"}},
                        "group_kind": {
                            "type": "string",
                            "enum": ["x_thread_scroll", "x_feed_scroll", "single_post", "mixed_or_unclear"],
                        },
                        "root_hint": {"type": "string", "maxLength": 300},
                        "overlap_notes": {"type": "string", "maxLength": 900},
                        "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    },
                    "required": ["group_id", "screenshot_indexes", "group_kind", "root_hint", "overlap_notes", "confidence"],
                },
            },
            "reconstructed_threads": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "manual_thread_id": {"type": "string", "maxLength": 100},
                        "source_group_id": {"type": "string", "maxLength": 80},
                        "thread_title": {"type": "string", "maxLength": 200},
                        "root_author_name": {"type": "string", "maxLength": 120},
                        "root_username": {"type": "string", "maxLength": 80},
                        "observed_post_time": {"type": "string", "maxLength": 80},
                        "root_text": {"type": "string", "maxLength": 5000},
                        "source_screenshot_indexes": {"type": "array", "maxItems": 20, "items": {"type": "integer"}},
                        "posts": {"type": "array", "maxItems": 120, "items": post_schema},
                        "merge_notes": {"type": "string", "maxLength": 1200},
                        "uncertainties": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 240}},
                    },
                    "required": [
                        "manual_thread_id",
                        "source_group_id",
                        "thread_title",
                        "root_author_name",
                        "root_username",
                        "observed_post_time",
                        "root_text",
                        "source_screenshot_indexes",
                        "posts",
                        "merge_notes",
                        "uncertainties",
                    ],
                },
            },
            "unresolved_fragments": {"type": "array", "maxItems": 30, "items": {"type": "string", "maxLength": 300}},
            "evidence_limits": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 240}},
        },
        "required": ["bundle_id", "stitch_groups", "reconstructed_threads", "unresolved_fragments", "evidence_limits"],
    }


def build_reconstruction_prompt(record: dict[str, Any]) -> str:
    screenshot_lines = []
    for screenshot in record["screenshots"]:
        screenshot_lines.append(
            " - ".join(
                [
                    f"index {screenshot['index']}",
                    screenshot["original_filename"],
                    f"size {screenshot.get('width') or '?'}x{screenshot.get('height') or '?'}",
                    f"captured {screenshot.get('embedded_datetime') or 'unknown'}",
                ]
            )
        )
    handles = [SOURCE_PROFILE.username, *SOURCE_PROFILE.alternate_usernames]
    visible_handles = ", ".join(f"@{item}" for item in handles if item)
    source_account_line = f"The configured source account is {source_label(SOURCE_PROFILE)}"
    if visible_handles:
        source_account_line += f"; visible handles may include {visible_handles}."
    else:
        source_account_line += "."
    return "\n".join(
        [
            "Reconstruct X/Twitter threads from a set of manual screenshots.",
            "First, logically stitch screenshots into scroll groups by matching overlaps, repeated posts, visible reply chains, timestamps, and root posts.",
            "A screenshot set may contain more than one thread. Create separate reconstructed_threads when roots or reply contexts differ.",
            "Merge duplicate/overlapping posts, but keep screenshot indexes as evidence.",
            "Preserve only visible text. Do not invent missing cut-off text. Mark starts_cut_off or ends_cut_off when the screenshot cuts a post.",
            "The screenshots themselves are source records. Images embedded inside visible X posts are embedded media; describe their visible content on that post.",
            "Treat charts, article cards, dashboard screenshots, and photos inside X posts as embedded_media with concise OCR/description.",
            "Do not infer investment signal, priority, portfolio action, or correctness. This pass only reconstructs source evidence.",
            f"{source_account_line} Mark source-account fields true only for those visible usernames/names.",
            "",
            f"Bundle id: {record['bundle_id']}",
            "Screenshots:",
            *screenshot_lines,
        ]
    )


def analyze_bundle_with_openai(record: dict[str, Any], model: str) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    content: list[dict[str, Any]] = [{"type": "input_text", "text": build_reconstruction_prompt(record)}]
    for screenshot in record["screenshots"]:
        content.append(
            {
                "type": "input_text",
                "text": f"Screenshot index {screenshot['index']}: {screenshot['original_filename']}",
            }
        )
        content.append({"type": "input_image", "image_url": image_data_url(Path(screenshot["imported_path"]))})
    reconstruction, _ = call_responses_json(
        api_key=api_key,
        model=model,
        system_prompt=(
            "You reconstruct visible X threads from manual screenshot evidence. "
            "Group overlapping scroll screenshots, merge duplicates, describe embedded media, "
            "and never invent missing text or investment conclusions. Output valid JSON only."
        ),
        user_content=content,
        schema_name="manual_x_thread_reconstruction",
        schema=reconstruction_schema(),
        max_output_tokens=12000,
        timeout=180,
    )
    return reconstruction


def import_manual_thread_bundle(args: argparse.Namespace) -> int:
    load_env(Path(args.env).expanduser())
    configure_source(load_x_source_profile(args.source_config, args.source_id))
    sources = normalize_sources(args.paths, args.source)
    output_dir = Path(args.output_dir).expanduser()
    bundle_id = slugify(args.bundle_id) if args.bundle_id else bundle_id_for(sources, args.bundle_name)
    model = args.model or os.environ.get("OPENAI_MANUAL_THREAD_MODEL") or DEFAULT_OPENAI_MODEL
    reporter = start_reporter(
        "manual_thread_import",
        total=len(sources),
        every_items=5,
        every_seconds=30,
        mode="dry_run" if args.dry_run else "import",
        output_dir=output_dir,
        bundle_id=bundle_id,
        analyze=bool(args.analyze),
        model=model if args.analyze else "",
    )
    record = build_bundle_record(
        bundle_id=bundle_id,
        bundle_name=args.bundle_name,
        sources=sources,
        output_dir=output_dir,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        for screenshot in record["screenshots"]:
            print(f"Would import {screenshot['source_path']} -> {screenshot['imported_path']}")
        if args.analyze:
            print("Would run manual thread reconstruction after import.")
        reporter.done(bundle_path=bundle_path(output_dir, bundle_id), screenshots=len(record["screenshots"]))
        return 0

    path = write_bundle(record, sources, output_dir, force=args.force)
    reporter.checkpoint(processed=len(sources), force=True, bundle_path=path)
    if args.analyze:
        reconstruction = analyze_bundle_with_openai(record, model)
        if not reconstruction:
            reporter.fail(bundle_path=path, reason="OPENAI_API_KEY is not configured")
            return 1
        record["analysis_stage"] = "manual_reconstruction_complete"
        record["status"] = "reconstructed"
        record["reconstruction"] = reconstruction
        record["stitch_groups"] = reconstruction.get("stitch_groups") or []
        record["reconstructed_threads"] = reconstruction.get("reconstructed_threads") or []
        record["reconstructed_at"] = iso_now()
        record["model"] = model
        input_tokens = int(reconstruction.get("_input_tokens") or 0)
        output_tokens = int(reconstruction.get("_output_tokens") or 0)
        record["estimated_openai_cost_usd"] = estimate_openai_cost_usd(model, input_tokens, output_tokens)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        reporter.done(
            bundle_path=path,
            stitch_groups=len(record["stitch_groups"]),
            reconstructed_threads=len(record["reconstructed_threads"]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_openai_cost_usd=record["estimated_openai_cost_usd"],
        )
    else:
        reporter.done(bundle_path=path, screenshots=len(record["screenshots"]))
    print(f"BUNDLE_PATH={path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import manual X screenshot sets and optionally reconstruct threads from overlapping screenshots."
    )
    parser.add_argument("paths", nargs="*", help="Screenshot image paths.")
    parser.add_argument("--source", action="append", default=[], help="Screenshot image path; may be repeated.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--env", default=".env")
    parser.add_argument("--source-config", default="config/sources/x_accounts.json")
    parser.add_argument("--source-id", default="")
    parser.add_argument("--bundle-id", default="")
    parser.add_argument("--bundle-name", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--analyze", action="store_true", help="Run OpenAI reconstruction after importing screenshots.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing bundle with the same id.")
    parser.add_argument("--dry-run", action="store_true")
    return import_manual_thread_bundle(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
