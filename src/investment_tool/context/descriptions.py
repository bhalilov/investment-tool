#!/usr/bin/env python3
"""Describe downloaded X media files with a neutral visual-analysis pass."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Sequence

from investment_tool.analysis.openai import call_responses_json
from investment_tool.runtime.config import (
    DEFAULT_X_MODULE_ID,
    FeedProfile,
    default_feed_config,
    feed_identity,
    load_pipeline_config,
    load_prompt,
    load_x_feed_profile,
    read_json,
    resolve_ai_model,
)
from investment_tool.runtime.env import load_env
from investment_tool.runtime.paths import portable_path, resolve_portable_path, storage_paths
from investment_tool.runtime.reporting import estimate_openai_cost_usd, start_reporter


PIPELINE_ID = "media_description"
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
FEED_PROFILE: FeedProfile = load_x_feed_profile()


def configure_feed(profile: FeedProfile) -> None:
    global FEED_PROFILE
    FEED_PROFILE = profile


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def media_key(path: Path) -> str:
    return path.stem


def media_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def media_output_path(output_dir: Path, path: Path) -> Path:
    return output_dir / f"{media_key(path)}.json"


def iter_media_paths(media_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in media_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def load_existing(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def should_skip(path: Path, out_path: Path, force: bool) -> bool:
    if force:
        return False
    existing = load_existing(out_path)
    if not existing:
        return False
    return existing.get("file_sha256") == media_fingerprint(path) and bool(existing.get("analysis"))


def build_media_prompt(path: Path, prompt_text: str) -> str:
    return "\n".join(
        [
            prompt_text.strip(),
            "",
            f"Media file: {path.name}",
            f"Media key: {media_key(path)}",
        ]
    )


def analyze_media_with_openai(
    path: Path,
    model: str,
    prompt_text: str,
    schema: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    analysis, _ = call_responses_json(
        api_key=api_key,
        model=model,
        system_prompt=(
            "You perform neutral OCR and visual description for investment screenshots. "
            "Never infer trading action or feed-account intent. Output valid JSON only."
        ),
        user_content=[
            {"type": "input_text", "text": build_media_prompt(path, prompt_text)},
            {"type": "input_image", "image_url": image_data_url(path)},
        ],
        schema_name="media_visual_observation",
        schema=schema,
        max_output_tokens=max_output_tokens,
        timeout=90,
    )
    return analysis


def build_record(path: Path, analysis: dict[str, Any] | None, model: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "media_key": media_key(path),
        "original_path": portable_path(path),
        "filename": path.name,
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "file_size": stat.st_size,
        "file_sha256": media_fingerprint(path),
        "analysis_stage": "media_visual_observation",
        "authority": "visual_extraction",
        "ocr_or_description_only": True,
        "model": model,
        "feed": feed_identity(FEED_PROFILE),
        "analyzed_at": iso_now() if analysis else "",
        "analysis": analysis,
    }


def sync_media_analysis(args: argparse.Namespace) -> int:
    load_env(Path(args.env).expanduser())
    configure_feed(load_x_feed_profile(args.feed_config, args.feed_id))
    storage = storage_paths()
    pipeline = load_pipeline_config(PIPELINE_ID)
    model = resolve_ai_model(PIPELINE_ID, args.model, ("OPENAI_MEDIA_MODEL",))
    prompt_path = args.prompt or str(pipeline["prompt"])
    schema_path = args.schema or str(pipeline["schema"])
    max_output_tokens = int(pipeline["max_output_tokens"])
    prompt = load_prompt(prompt_path)
    schema = read_json(schema_path)
    media_dir = resolve_portable_path(args.media_dir) if args.media_dir else storage.x_media
    output_dir = resolve_portable_path(args.output_dir) if args.output_dir else storage.x_descriptions
    paths = iter_media_paths(media_dir)
    if args.media_key:
        wanted = {key.strip() for key in args.media_key if key.strip()}
        paths = [path for path in paths if media_key(path) in wanted]
    if args.limit:
        paths = paths[: args.limit]
    reporter = start_reporter(
        "descriptions",
        total=len(paths),
        every_items=10,
        every_seconds=30,
        mode="dry_run" if args.dry_run else "sync",
        media_dir=portable_path(media_dir),
        output_dir=portable_path(output_dir),
        model=model,
        prompt_path=prompt["path"],
        prompt_sha256=prompt["sha256"],
        schema=schema_path,
        pipeline=PIPELINE_ID,
    )
    stats = {
        "seen": 0,
        "analyzed": 0,
        "skipped": 0,
        "failed": 0,
        "written": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        stats["seen"] += 1
        out_path = media_output_path(output_dir, path)
        try:
            if should_skip(path, out_path, args.force):
                stats["skipped"] += 1
                continue
            if args.dry_run:
                print(f"Would analyze {path} -> {out_path}")
                stats["skipped"] += 1
                continue
            reporter.emit("WAITING", reason="openai_media_analysis", path=path.name, timeout_seconds=90, model=model)
            analysis = analyze_media_with_openai(path, model, prompt["text"], schema, max_output_tokens)
            if not analysis:
                stats["failed"] += 1
                reporter.emit("ERROR", path=path.name, reason="missing_openai_api_key_or_empty_analysis")
                continue
            analysis["input_fingerprint"] = media_fingerprint(path)
            stats["analyzed"] += 1
            stats["input_tokens"] += int(analysis.get("_input_tokens") or 0)
            stats["output_tokens"] += int(analysis.get("_output_tokens") or 0)
            record = build_record(path, analysis, model)
            out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            stats["written"] += 1
            reporter.checkpoint_stats(stats, processed=stats["seen"], path=path.name)
        except Exception as exc:
            stats["failed"] += 1
            reporter.emit("ERROR", path=path.name, error=str(exc), failed=stats["failed"])
    cost = estimate_openai_cost_usd(model, stats["input_tokens"], stats["output_tokens"])
    manifest = {
        "generated_at": iso_now(),
        "media_dir": portable_path(media_dir),
        "output_dir": portable_path(output_dir),
        "model": model,
        "prompt_path": prompt["path"],
        "prompt_sha256": prompt["sha256"],
        "schema": schema_path,
        "pipeline": PIPELINE_ID,
        **stats,
        "estimated_openai_cost_usd": cost,
    }
    if not args.dry_run:
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    reporter.done(**manifest)
    for key, value in manifest.items():
        print(f"{key.upper()}={value}")
    return 0 if stats["failed"] == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze downloaded X media into reusable neutral visual descriptions.")
    parser.add_argument("--media-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--feed-config", default=default_feed_config(DEFAULT_X_MODULE_ID))
    parser.add_argument("--feed-id", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--schema", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--media-key", action="append", default=[], help="Analyze only this media key; may be repeated.")
    parser.add_argument("--force", action="store_true", help="Re-analyze even when output exists for the same image hash.")
    parser.add_argument("--dry-run", action="store_true")
    return sync_media_analysis(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
