"""Stored X thread JSON/HTML lifecycle helpers."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from investment_tool.presentation.indexes import render_all_indexes
from investment_tool.runtime.paths import portable_path, resolve_portable_path
from investment_tool.rules.tickers import ticker_bucket_payload
from investment_tool.rules.filters import primary_label
from investment_tool.feeds.x.context import XCaptureContext
from investment_tool.feeds.x.metadata import (
    CATEGORY_VALUES,
    PRIORITY_VALUES,
    SIGNAL_VALUES,
    STANCE_VALUES,
    analysis_field_payload,
    apply_pending_safe_summary,
    base_thread_metadata,
    classify_thread,
    compact_text,
    ignore_reason,
    infer_tags,
    media_placeholder_tags,
    non_photo_media_placeholders,
    normalize_enum,
    root_post_tickers,
    root_primary_tickers,
    rough_tldr,
    safe_slug,
    feed_conversation_tickers,
    thread_created_at,
    thread_title,
    title_with_label_prefix,
)
from investment_tool.feeds.x.threads import (
    display_text,
    media_keys,
    thread_local_media,
    thread_local_media_paths,
    thread_media_keys,
)
from investment_tool.presentation.threads import date_prefix, render_thread_html


DEFAULT_OWNED_POSITIONS_FILE = Path("config/owned_positions.json")


def load_cached_threads(
    json_dir: Path,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
) -> dict[str, set[str]]:
    """Load previously captured thread JSONs into in-memory API maps."""
    cached: dict[str, set[str]] = {}
    for json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        conv_id = data.get("conversation_id")
        if not conv_id:
            continue
        tweet_ids: set[str] = set()
        for tweet in data.get("tweets") or []:
            tweets[tweet["id"]] = tweet
            tweet_ids.add(tweet["id"])
        users.update(data.get("users") or {})
        media.update(data.get("media") or {})
        cached[conv_id] = tweet_ids
    return cached


def find_cached_thread_record(json_dir: Path, conversation_id: str) -> tuple[Path, dict] | None:
    """Return the existing thread JSON for a conversation, if one exists."""
    for json_path in sorted(json_dir.glob(f"*__{conversation_id}.json")):
        try:
            return json_path, json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def cleanup_old_thread_versions(json_dir: Path, threads_dir: Path, conversation_id: str, keep_json: Path, keep_html: Path) -> None:
    """Remove older HTML/JSON versions for a conversation after canonical naming changes."""
    for json_path in json_dir.glob(f"*__{conversation_id}.json"):
        if json_path.resolve() == keep_json.resolve():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            old_filename = data.get("canonical_filename")
        except Exception:
            old_filename = None
        if old_filename:
            old_html = threads_dir / old_filename
            if old_html.exists() and old_html.resolve() != keep_html.resolve():
                old_html.unlink()
        json_path.unlink(missing_ok=True)
    for html_path in threads_dir.glob(f"*__{conversation_id}.html"):
        if html_path.resolve() != keep_html.resolve():
            html_path.unlink()


def load_owned_tickers() -> set[str]:
    configured = os.environ.get("OWNED_POSITIONS_FILE", "").strip()
    path = resolve_portable_path(configured) if configured else Path.cwd() / DEFAULT_OWNED_POSITIONS_FILE
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN: Could not read owned positions file {path}: {exc}", file=sys.stderr)
        return set()
    if isinstance(data, list):
        raw_tickers = data
    else:
        raw_tickers = data.get("owned_tickers") or data.get("tickers") or []
    return {str(ticker).upper().strip() for ticker in raw_tickers if str(ticker).strip()}


def write_ignored_record(root: Path, conversation_id: str, reason: str, data: dict, context: XCaptureContext) -> None:
    ignored_dir = root / "ignored"
    ignored_dir.mkdir(parents=True, exist_ok=True)
    tweets = data.get("tweets") or []
    feed_posts = [tweet for tweet in tweets if tweet.get("author_id") == context.user_id]
    root_tweet = next((tweet for tweet in tweets if tweet.get("id") == conversation_id), None)
    record = {
        "conversation_id": conversation_id,
        "reason": reason,
        "title": data.get("title"),
        "canonical_filename": data.get("canonical_filename"),
        "type": data.get("type"),
        "tickers": data.get("tickers") or [],
        "tags": data.get("tags") or [],
        "posts": len(tweets),
        "feed_posts": len(feed_posts),
        "root_author_id": (root_tweet or {}).get("author_id"),
        "sample_text": compact_text(display_text(feed_posts[0] if feed_posts else root_tweet or {}), 500),
        "feed": context.feed_record(kind="ignored_thread_record"),
        "ignored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (ignored_dir / f"{conversation_id}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def remove_thread_htmls(threads_dir: Path, conversation_id: str, filename: str | None = None) -> None:
    if filename:
        (threads_dir / filename).unlink(missing_ok=True)
    for html_path in threads_dir.glob(f"*__{conversation_id}.html"):
        html_path.unlink(missing_ok=True)


def move_generated_json_to_ignored(
    root: Path,
    json_path: Path,
    threads_dir: Path,
    data: dict[str, Any],
    reason: str,
    context: XCaptureContext,
) -> None:
    conversation_id = str(data.get("conversation_id") or json_path.stem.rsplit("__", 1)[-1])
    data["ignored"] = True
    data["ignored_reason"] = reason
    data["ignored_at"] = data.get("ignored_at") or dt.datetime.now(dt.timezone.utc).isoformat()
    write_ignored_record(root, conversation_id, reason, data, context)
    remove_thread_htmls(threads_dir, conversation_id, data.get("canonical_filename"))
    json_path.unlink(missing_ok=True)


def entries_from_cached_json(json_dir: Path, threads_dir: Path, context: XCaptureContext) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        conv_id = data.get("conversation_id")
        if not conv_id:
            continue
        if data.get("ignored"):
            continue
        filename = data.get("canonical_filename", "")
        html_path = threads_dir / filename if filename else None
        if not html_path or not html_path.exists():
            continue
        prefix = json_path.stem.split("__")[0]
        date = f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}" if len(prefix) == 8 else data.get("captured_at", "")[:10]
        tweets = data.get("tweets", [])
        root_tweet = next((tweet for tweet in tweets if tweet.get("id") == conv_id), None)
        created_at = data.get("created_at") or thread_created_at(root_tweet, tweets) or data.get("captured_at", date)
        tickers = data.get("tickers", [])
        entries.append(
            {
                "type": data.get("type", ""),
                "title": data.get("title", conv_id),
                "date": date,
                "created_at": created_at,
                "captured_at": data.get("captured_at", created_at),
                "label": data.get("primary_label", "UNKNOWN"),
                "tickers": tickers,
                "tags": data.get("tags", []),
                "priority": normalize_enum(data.get("priority"), PRIORITY_VALUES, ""),
                "signal": normalize_enum(data.get("signal"), SIGNAL_VALUES, ""),
                "category": normalize_enum(data.get("category"), CATEGORY_VALUES, ""),
                "stance": normalize_enum(data.get("stance"), STANCE_VALUES, ""),
                "actionability_score": data.get("actionability_score"),
                "flags": data.get("flags", []),
                "primary_ticker": data.get("primary_ticker") or (tickers[0] if tickers else "UNKNOWN"),
                "conversation_id": conv_id,
                "abs_path": str(html_path),
                "posts": len(tweets),
                "feed_posts": sum(1 for tweet in tweets if tweet.get("author_id") == context.user_id),
                "photos": sum(len(media_keys(tweet)) for tweet in tweets),
                **context.feed_entry_fields(data),
            }
        )
    return entries


def apply_cached_relevance_gate(root: Path, json_dir: Path, threads_dir: Path, context: XCaptureContext) -> int:
    ignored = 0
    for json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        conv_id = data.get("conversation_id")
        if not conv_id:
            continue
        items = data.get("tweets") or []
        root_tweet = next((item for item in items if item.get("id") == conv_id), None)
        tickers = data.get("tickers") or []
        thread_type = data.get("type") or classify_thread(root_tweet, items, context)
        reason = ignore_reason(root_tweet, items, thread_type, tickers, context)
        if not reason:
            continue
        move_generated_json_to_ignored(root, json_path, threads_dir, data, reason, context)
        ignored += 1
    return ignored


def rerender_cached_threads(
    root: Path,
    json_dir: Path,
    threads_dir: Path,
    conversation_id: str | None,
    context: XCaptureContext,
    presentation_root: Path | None = None,
) -> list[dict[str, Any]]:
    index_root = presentation_root or root
    entries: list[dict[str, Any]] = []
    for source_json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(source_json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        conv_id = data.get("conversation_id")
        if not conv_id or (conversation_id and conv_id != conversation_id):
            continue
        if data.get("ignored"):
            move_generated_json_to_ignored(root, source_json_path, threads_dir, data, data.get("ignored_reason") or "IGNORED", context)
            continue
        items = data.get("tweets") or []
        users = data.get("users") or {}
        media = data.get("media") or {}
        media_paths = data.get("media_paths") or {}
        local_media = thread_local_media(media, items)
        local_media_paths = thread_local_media_paths(media_paths, items)
        root_tweet = next((item for item in items if item.get("id") == conv_id), None)
        created_at = thread_created_at(root_tweet, items)
        title, _slug = thread_title(root_tweet, items)
        op_tickers = root_post_tickers(root_tweet)
        metadata_tickers = root_primary_tickers(root_tweet)
        relevance_tickers = feed_conversation_tickers(root_tweet, items, context)
        thread_type = classify_thread(root_tweet, items, context)
        tags = list(dict.fromkeys(infer_tags(items, thread_type, metadata_tickers, context) + media_placeholder_tags(items, local_media, context)))
        label = primary_label(metadata_tickers, tags)
        title = title_with_label_prefix(title, label)
        reason = ignore_reason(root_tweet, items, thread_type, relevance_tickers, context)
        if reason:
            move_generated_json_to_ignored(root, source_json_path, threads_dir, data, reason, context)
            continue
        tldr = rough_tldr(items, context.user_id)
        analysis = data.get("analysis")
        analysis_metadata = base_thread_metadata(title, label, op_tickers, tags, tldr, data)
        title = analysis_metadata["title"]
        label = analysis_metadata["primary_label"]
        tickers = analysis_metadata["tickers"]
        tags = analysis_metadata["tags"]
        tldr = analysis_metadata["tldr"]
        slug = safe_slug(title.split(" - ", 1)[-1] if " - " in title else title)
        prefix = date_prefix(root_tweet, items)
        filename = f"{prefix}__{label}__{slug}__{conv_id}.html"
        html_path = threads_dir / filename
        json_path = json_dir / f"{prefix}__{label}__{slug}__{conv_id}.json"
        cleanup_old_thread_versions(json_dir, threads_dir, conv_id, json_path, html_path)
        render_thread_html(
            html_path,
            conv_id,
            title,
            thread_type,
            label,
            tickers,
            tags,
            tldr,
            analysis_metadata,
            json_path,
            items,
            users,
            local_media,
            local_media_paths,
            0,
            index_root,
            context.username,
            context.user_id,
        )
        updated = apply_pending_safe_summary(
            {
                **data,
                "title": title,
                "canonical_filename": filename,
                "canonical_json_filename": json_path.name,
                "created_at": created_at,
                "type": thread_type,
                "primary_label": label,
                "tickers": tickers,
                "tags": tags,
                **analysis_field_payload(analysis_metadata),
                "analysis": analysis,
                "analysis_stage": data.get("analysis_stage") or "captured_pending_ai_pass1",
                "media": local_media,
                "media_paths": local_media_paths,
                "non_photo_media": non_photo_media_placeholders(items, local_media, context),
            },
            analysis_metadata,
        )
        json_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
        entries.append(
            {
                "type": thread_type,
                "title": title,
                "date": f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}",
                "created_at": created_at,
                "captured_at": updated.get("captured_at", f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}"),
                "label": label,
                "tickers": tickers,
                "tags": tags,
                "priority": analysis_metadata.get("priority") or "",
                "signal": analysis_metadata.get("signal") or "",
                "category": analysis_metadata.get("category") or "",
                "stance": analysis_metadata.get("stance") or "",
                "actionability_score": analysis_metadata.get("actionability_score"),
                "flags": analysis_metadata.get("flags", []),
                "primary_ticker": analysis_metadata.get("primary_ticker", "UNKNOWN"),
                "conversation_id": conv_id,
                "abs_path": str(html_path),
                "posts": len(items),
                "feed_posts": sum(1 for item in items if item.get("author_id") == context.user_id),
                "photos": sum(len(media_keys(item)) for item in items),
                **context.feed_entry_fields(updated),
            }
        )
    if conversation_id:
        processed = {entry["conversation_id"] for entry in entries}
        entries.extend(entry for entry in entries_from_cached_json(json_dir, threads_dir, context) if entry["conversation_id"] not in processed)
    return entries or entries_from_cached_json(json_dir, threads_dir, context)


def repair_cached_media_paths(json_dir: Path, backup_root: Path) -> dict[str, int | str]:
    backup_dir = backup_root / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_media_path_repair")
    stats = {
        "scanned": 0,
        "changed": 0,
        "unchanged": 0,
        "failed": 0,
        "removed_media_path_refs": 0,
        "media_free_paths_cleared": 0,
        "backup_dir": portable_path(backup_dir),
    }
    for path in sorted(json_dir.glob("*.json")):
        stats["scanned"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("tweets") or []
            if not isinstance(items, list):
                stats["unchanged"] += 1
                continue
            before_paths = data.get("media_paths") or {}
            before_media = data.get("media") or {}
            if not isinstance(before_paths, dict):
                before_paths = {}
            if not isinstance(before_media, dict):
                before_media = {}
            after_paths = thread_local_media_paths(before_paths, items)
            after_media = thread_local_media(before_media, items)
            if before_paths == after_paths and before_media == after_media:
                stats["unchanged"] += 1
                continue
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            actual_keys = thread_media_keys(items)
            if before_paths and not actual_keys:
                stats["media_free_paths_cleared"] += 1
            stats["removed_media_path_refs"] += max(0, len(before_paths) - len(after_paths))
            data["media_paths"] = after_paths
            data["media"] = after_media
            data["media_paths_repaired_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            stats["changed"] += 1
        except Exception as exc:
            stats["failed"] += 1
            print(f"ERROR: Failed to repair media paths in {path}: {exc}", file=sys.stderr)
    return stats


def render_cached_indexes(
    root: Path,
    json_dir: Path,
    threads_dir: Path,
    context: XCaptureContext,
    presentation_root: Path | None = None,
) -> tuple[list[dict[str, Any]], int]:
    ignored = apply_cached_relevance_gate(root, json_dir, threads_dir, context)
    entries = entries_from_cached_json(json_dir, threads_dir, context)
    render_all_indexes(presentation_root or root, entries, load_owned_tickers())
    return entries, ignored
