"""Rebuild X thread records from saved raw API responses."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from investment_tool.rules.filters import primary_label
from investment_tool.rules.tickers import ticker_bucket_payload
from investment_tool.sources.x.context import XCaptureContext
from investment_tool.sources.x.metadata import (
    classify_thread,
    compact_text,
    ignore_reason,
    infer_tags,
    media_placeholder_tags,
    non_photo_media_placeholders,
    root_post_tickers,
    root_primary_tickers,
    rough_tldr,
    safe_slug,
    source_conversation_tickers,
    thread_created_at,
    thread_title,
    title_with_label_prefix,
)
from investment_tool.sources.x.raw import load_raw_api_archive
from investment_tool.sources.x.threads import (
    display_text,
    existing_local_media_paths,
    missing_media_keys,
    quoted_ids,
    thread_local_media,
    thread_local_media_paths,
    thread_user_map,
)
from investment_tool.presentation.threads import date_prefix


def conversation_ids_from_raw_tweets(tweets: dict[str, dict], context: XCaptureContext) -> set[str]:
    return {
        str(tweet["conversation_id"])
        for tweet in tweets.values()
        if tweet.get("author_id") == context.user_id and tweet.get("conversation_id")
    }


def group_raw_conversations(
    tweets: dict[str, dict],
    conversation_ids: set[str],
    context: XCaptureContext,
) -> dict[str, list[dict]]:
    by_conversation: dict[str, list[dict]] = defaultdict(list)
    for tweet in tweets.values():
        conv = tweet.get("conversation_id")
        if conv in conversation_ids:
            by_conversation[str(conv)].append(tweet)
    for conversation_id, items in list(by_conversation.items()):
        included_ids = {item.get("id") for item in items}
        for item in list(items):
            if item.get("author_id") != context.user_id and item.get("id") != conversation_id:
                continue
            for quoted_id in quoted_ids(item):
                quoted = tweets.get(quoted_id)
                if quoted and quoted_id not in included_ids:
                    by_conversation[conversation_id].append(quoted)
                    included_ids.add(quoted_id)
        by_conversation[conversation_id] = sorted(
            by_conversation[conversation_id],
            key=lambda item: (item.get("created_at") or "", item.get("id") or ""),
        )
    return by_conversation


def clean_raw_rebuilt_thread_record(
    conversation_id: str,
    items: list[dict],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    all_media_paths: dict[str, str],
    context: XCaptureContext,
) -> tuple[dict[str, Any], str, str]:
    root_tweet = tweets.get(conversation_id)
    title, slug = thread_title(root_tweet, items)
    source_items = [item for item in items if item.get("author_id") == context.user_id]
    op_tickers = root_post_tickers(root_tweet)
    metadata_tickers = root_primary_tickers(root_tweet)
    relevance_tickers = source_conversation_tickers(root_tweet, items, context)
    thread_type = classify_thread(root_tweet, items, context)
    local_media = thread_local_media(media, items)
    local_paths = thread_local_media_paths(all_media_paths, items)
    tags = list(dict.fromkeys(infer_tags(items, thread_type, metadata_tickers, context) + media_placeholder_tags(items, local_media, context)))
    label = primary_label(metadata_tickers, tags)
    title = title_with_label_prefix(title, label)
    reason = ignore_reason(root_tweet, items, thread_type, relevance_tickers, context)
    prefix = date_prefix(root_tweet, items)
    filename = f"{prefix}__{label}__{safe_slug(slug)}__{conversation_id}.json"
    record: dict[str, Any] = {
        "conversation_id": conversation_id,
        "title": title,
        "canonical_json_filename": filename,
        "created_at": thread_created_at(root_tweet, items),
        "type": thread_type,
        "primary_label": label,
        "tickers": metadata_tickers,
        **ticker_bucket_payload(op_tickers),
        "tags": tags,
        "preview_text": rough_tldr(items, context.user_id),
        "analysis_stage": "raw_rebuilt_pending_media_description",
        "completeness_status": "rebuilt_from_saved_raw_api",
        "rebuilt_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tweets": items,
        "users": thread_user_map(items, users),
        "media": local_media,
        "media_paths": local_paths,
        "non_photo_media": non_photo_media_placeholders(items, local_media, context),
        "missing_media": missing_media_keys(items, local_media, local_paths),
        "source": context.source_record(kind="saved_x_raw_api_rebuild", raw_api_used=True, x_api_called=False),
    }
    if reason:
        record["ignored"] = True
        record["ignored_reason"] = reason
        record["sample_text"] = compact_text(display_text(source_items[0] if source_items else root_tweet or {}), 500)
    return record, filename, reason or ""


def replace_generated_thread_jsons(root: Path, staging_dir: Path) -> None:
    for path in (root / "thread_json").glob("*.json"):
        path.unlink(missing_ok=True)
    for path in (root / "ignored").glob("*.json"):
        path.unlink(missing_ok=True)
    for dated_thread_dir in root.glob("20??-??-??/thread_json"):
        if dated_thread_dir.is_dir():
            for path in dated_thread_dir.glob("*.json"):
                path.unlink(missing_ok=True)
    backup_root = root / "cleanup_backups"
    if backup_root.exists():
        shutil.rmtree(backup_root)
    (root / "thread_json").mkdir(parents=True, exist_ok=True)
    (root / "ignored").mkdir(parents=True, exist_ok=True)
    for src in (staging_dir / "thread_json").glob("*.json"):
        shutil.copy2(src, root / "thread_json" / src.name)
    for src in (staging_dir / "ignored").glob("*.json"):
        shutil.copy2(src, root / "ignored" / src.name)


def rebuild_from_raw_api(
    root: Path,
    staging_dir: Path,
    replace_active: bool,
    context: XCaptureContext,
) -> dict[str, Any]:
    raw_root = root / "raw_api"
    media_dir = root / "media"
    tweets, users, media, raw_stats = load_raw_api_archive(raw_root)
    media_paths = existing_local_media_paths(media_dir)
    conversation_ids = conversation_ids_from_raw_tweets(tweets, context)
    by_conversation = group_raw_conversations(tweets, conversation_ids, context)
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    thread_dir = staging_dir / "thread_json"
    ignored_dir = staging_dir / "ignored"
    thread_dir.mkdir(parents=True, exist_ok=True)
    ignored_dir.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {
        **raw_stats,
        "unique_tweets": len(tweets),
        "unique_users": len(users),
        "unique_media": len(media),
        "local_media_files": len(media_paths),
        "candidate_conversations": len(conversation_ids),
        "written_threads": 0,
        "written_ignored": 0,
        "missing_media_refs": 0,
        "ignored_reasons": {},
        "staging_dir": str(staging_dir),
        "replace_active": replace_active,
    }
    ignored_reasons: Counter[str] = Counter()
    for conversation_id in sorted(
        by_conversation,
        key=lambda conv: thread_created_at(tweets.get(conv), by_conversation[conv]) or "",
    ):
        record, filename, reason = clean_raw_rebuilt_thread_record(
            conversation_id,
            by_conversation[conversation_id],
            tweets,
            users,
            media,
            media_paths,
            context,
        )
        if reason:
            out_path = ignored_dir / f"{conversation_id}.json"
            stats["written_ignored"] += 1
            ignored_reasons[reason] += 1
        else:
            out_path = thread_dir / filename
            stats["written_threads"] += 1
        stats["missing_media_refs"] += len(record.get("missing_media") or [])
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    stats["ignored_reasons"] = dict(ignored_reasons)
    manifest = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "x_root": str(root),
        **stats,
    }
    (staging_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if replace_active:
        replace_generated_thread_jsons(root, staging_dir)
    return manifest
