"""Live X capture stage and X-specific maintenance helpers."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_tool.index_render import render_all_indexes
from investment_tool.reporting import JobReporter
from investment_tool.thread_filtering import primary_label
from investment_tool.ticker_parser import ticker_bucket_payload
from investment_tool.x_capture_context import XCaptureContext
from investment_tool.x_capture_metadata import (
    analysis_field_payload,
    apply_pending_safe_summary,
    base_thread_metadata,
    classify_thread,
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
from investment_tool.x_client import (
    XClient,
    download_photos,
    fetch_timeline,
    fetch_tweets_by_ids,
    fetch_tweets_by_ids_even_if_cached,
    refresh_x_user_token,
    search_conversation,
)
from investment_tool.x_raw_archive import load_raw_api_archive
from investment_tool.x_thread_model import (
    explicit_x_links,
    media_keys,
    parent_id,
    quoted_ids,
    referenced_ids,
    thread_local_media,
    thread_local_media_paths,
)
from investment_tool.x_thread_render import date_prefix, render_thread_html
from investment_tool.x_thread_store import (
    cleanup_old_thread_versions,
    entries_from_cached_json,
    find_cached_thread_record,
    load_cached_threads,
    load_owned_tickers,
    move_generated_json_to_ignored,
    remove_thread_htmls,
    write_ignored_record,
)


DEFAULT_X_POST_READ_COST_USD = 0.005


@dataclass(frozen=True)
class XCaptureOptions:
    timeline_pages: int = 3
    conversation_pages: int = 5
    max_threads: int = 20
    conversation_id: str = ""
    force: bool = False


@dataclass(frozen=True)
class XCapturePaths:
    root: Path
    raw_dir: Path
    json_dir: Path
    media_dir: Path
    threads_dir: Path


def data_root() -> Path:
    return Path(os.environ.get("INVESTMENT_TOOL_DATA_DIR", "~/investment-tool-data")).expanduser()


def prepare_x_capture_paths(run_id: str) -> XCapturePaths:
    root = data_root() / "x_threads"
    paths = XCapturePaths(
        root=root,
        raw_dir=root / "raw_api" / run_id,
        json_dir=root / "thread_json",
        media_dir=root / "media",
        threads_dir=root / "threads",
    )
    for folder in (paths.raw_dir, paths.json_dir, paths.media_dir, paths.threads_dir, root / "indexes"):
        folder.mkdir(parents=True, exist_ok=True)
    return paths


def emit_checkpoint(reporter: JobReporter | None, name: str, **fields: object) -> None:
    if reporter:
        reporter.emit("CHECKPOINT", checkpoint=name, **fields)
    else:
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        print(f"CHECKPOINT {name}{(' ' + suffix) if suffix else ''}", flush=True)


def walk_context(
    client: XClient,
    seed_ids: list[str],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    depth_limit: int = 20,
) -> None:
    queue = list(dict.fromkeys(seed_ids))
    seen: set[str] = set()
    while queue:
        tweet_id = queue.pop(0)
        if tweet_id in seen:
            continue
        seen.add(tweet_id)
        if tweet_id not in tweets:
            fetch_tweets_by_ids(client, [tweet_id], tweets, users, media, "context_lookup")
        tweet = tweets.get(tweet_id)
        if not tweet:
            continue
        for ref_id in referenced_ids(tweet):
            if ref_id not in seen:
                queue.append(ref_id)
        for linked_id in explicit_x_links(tweet):
            if linked_id not in seen:
                queue.append(linked_id)

        current = tweet
        for _ in range(depth_limit):
            pid = parent_id(current)
            if not pid or pid in seen:
                break
            if pid not in tweets:
                fetch_tweets_by_ids(client, [pid], tweets, users, media, "parent_chain")
            parent = tweets.get(pid)
            if not parent:
                break
            queue.append(pid)
            current = parent


def write_usage_estimate(root: Path, run_id: str, client: XClient) -> dict[str, Any]:
    usage_dir = root / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    cost_per_post = float(os.environ.get("X_POST_READ_COST_USD", DEFAULT_X_POST_READ_COST_USD))
    credit_start = float(os.environ.get("X_CREDIT_START_USD", "25"))
    unique_reads = len(client.post_ids_returned)
    estimated_cost = unique_reads * cost_per_post
    record = {
        "run_id": run_id,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "api_calls": client.call_count,
        "unique_post_ids_returned": unique_reads,
        "estimated_cost_usd": round(estimated_cost, 4),
        "cost_per_post_read_usd": cost_per_post,
        "credit_start_usd": credit_start,
        "estimated_remaining_if_starting_credit_applies_usd": round(max(0.0, credit_start - estimated_cost), 4),
        "note": "Rough estimate only. X billing uses daily deduplication and endpoint-specific pricing.",
    }
    with (usage_dir / "usage_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (usage_dir / "latest_usage_estimate.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def missing_media_metadata_targets(json_dir: Path, raw_media: dict[str, dict]) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = defaultdict(set)
    for json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        local_paths = data.get("media_paths") or {}
        if not isinstance(local_paths, dict):
            local_paths = {}
        for tweet in data.get("tweets") or []:
            tweet_id = tweet.get("id")
            if not tweet_id:
                continue
            for key in media_keys(tweet):
                if key in local_paths:
                    continue
                if key not in raw_media:
                    targets[str(tweet_id)].add(str(key))
    return targets


def recover_missing_media_metadata(root: Path, client: XClient, context: XCaptureContext) -> dict[str, Any]:
    json_dir = root / "thread_json"
    media_dir = root / "media"
    tweets, users, media, raw_stats = load_raw_api_archive(root / "raw_api")
    before_media_keys = set(media)
    targets = missing_media_metadata_targets(json_dir, media)
    target_tweet_ids = sorted(targets)
    target_media_keys = {key for keys in targets.values() for key in keys}
    stats: dict[str, Any] = {
        **raw_stats,
        "target_tweets": len(target_tweet_ids),
        "target_media_keys": len(target_media_keys),
        "x_api_calls_before": client.call_count,
        "recovered_media_metadata": 0,
        "recovered_photo_metadata": 0,
        "non_photo_metadata_ignored": 0,
        "downloaded_photos": 0,
        "still_missing_metadata": 0,
        "x_api_calls_after": 0,
    }
    if target_tweet_ids:
        fetch_tweets_by_ids_even_if_cached(client, target_tweet_ids, tweets, users, media, "recover_missing_media")
    recovered_keys = target_media_keys & set(media)
    stats["recovered_media_metadata"] = len(recovered_keys - before_media_keys)
    recovered_photo_keys = {key for key in recovered_keys if (media.get(key) or {}).get("type") == "photo"}
    stats["recovered_photo_metadata"] = len(recovered_photo_keys)
    placeholder_types = set(context.media_rules.get("placeholder_types") or ["video", "animated_gif"])
    stats["non_photo_metadata_ignored"] = sum(
        1 for key in recovered_keys if (media.get(key) or {}).get("type") in placeholder_types
    )
    if recovered_photo_keys:
        downloaded = download_photos(media, media_dir, recovered_photo_keys)
        stats["downloaded_photos"] = len(downloaded)
    stats["still_missing_metadata"] = len(target_media_keys - set(media))
    stats["x_api_calls_after"] = client.call_count
    stats["x_api_calls_used"] = client.call_count - int(stats["x_api_calls_before"])
    stats["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return stats


def run_live_x_capture(
    paths: XCapturePaths,
    run_id: str,
    env_path: Path,
    token: str,
    options: XCaptureOptions,
    context: XCaptureContext,
    reporter: JobReporter | None = None,
) -> dict[str, Any]:
    client = XClient(token, paths.raw_dir, refresh_callback=lambda: refresh_x_user_token(env_path))
    tweets: dict[str, dict] = {}
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}

    cached_tweet_ids = load_cached_threads(paths.json_dir, tweets, users, media)
    cached_conversation_ids = set(cached_tweet_ids.keys())
    if cached_conversation_ids:
        print(f"CACHED={len(cached_conversation_ids)} threads found locally")

    emit_checkpoint(reporter, "X_TIMELINE_FETCH_START", pages=options.timeline_pages)
    seed_ids = fetch_timeline(client, context.user_id, options.timeline_pages, tweets, users, media)
    emit_checkpoint(reporter, "X_TIMELINE_FETCH_DONE", seed_posts=len(seed_ids), total_posts=len(tweets), api_calls=client.call_count)
    if options.conversation_id:
        seed_ids.append(options.conversation_id)
        fetch_tweets_by_ids(client, [options.conversation_id], tweets, users, media, "requested_conversation")
        emit_checkpoint(reporter, "X_REQUESTED_CONVERSATION_FETCH_DONE", conversation_id=options.conversation_id, api_calls=client.call_count)
    emit_checkpoint(reporter, "X_CONTEXT_WALK_START", seed_posts=len(seed_ids))
    walk_context(client, seed_ids, tweets, users, media)
    emit_checkpoint(reporter, "X_CONTEXT_WALK_DONE", total_posts=len(tweets), users=len(users), media=len(media), api_calls=client.call_count)

    conversation_ids: list[str] = []
    if options.conversation_id:
        conversation_ids = [options.conversation_id]
    else:
        for tweet in sorted(tweets.values(), key=lambda item: item.get("created_at") or "", reverse=True):
            if tweet.get("author_id") != context.user_id:
                continue
            conv = tweet.get("conversation_id")
            if conv and conv not in conversation_ids:
                conversation_ids.append(conv)
            if len(conversation_ids) >= options.max_threads:
                break
    emit_checkpoint(reporter, "THREAD_DISCOVERY_DONE", conversations=len(conversation_ids), cached=len(cached_conversation_ids))

    def has_new_tweets(conv_id: str) -> bool:
        known = cached_tweet_ids.get(conv_id, set())
        current = {tid for tid, tweet in tweets.items() if tweet.get("conversation_id") == conv_id}
        return bool(current - known)

    search_counts: dict[str, int] = {}
    conversation_search_run = 0
    conversation_search_skipped = 0
    for conversation_id in conversation_ids:
        if not options.force and conversation_id in cached_conversation_ids and not has_new_tweets(conversation_id):
            search_counts[conversation_id] = 0
            conversation_search_skipped += 1
            continue
        conversation_search_run += 1
        emit_checkpoint(reporter, "X_CONVERSATION_SEARCH_START", conversation_id=conversation_id, pages=options.conversation_pages)
        search_counts[conversation_id] = search_conversation(
            client, conversation_id, tweets, users, media, options.conversation_pages
        )
        conv_ids = [tweet_id for tweet_id, tweet in tweets.items() if tweet.get("conversation_id") == conversation_id]
        walk_context(client, conv_ids, tweets, users, media)
        emit_checkpoint(
            reporter,
            "X_CONVERSATION_SEARCH_DONE",
            conversation_id=conversation_id,
            search_results=search_counts[conversation_id],
            conversation_posts=len(conv_ids),
            api_calls=client.call_count,
        )
    emit_checkpoint(reporter, "X_CONVERSATION_SEARCH_SUMMARY", searched=conversation_search_run, skipped_cached=conversation_search_skipped)

    by_conversation: dict[str, list[dict]] = defaultdict(list)
    for tweet in tweets.values():
        conv = tweet.get("conversation_id")
        if conv in conversation_ids:
            by_conversation[conv].append(tweet)
    for conversation_id, items in list(by_conversation.items()):
        included_ids = {item.get("id") for item in items}
        for item in list(items):
            if item.get("author_id") != context.user_id and item.get("id") != conversation_id:
                continue
            for qid in quoted_ids(item):
                quoted = tweets.get(qid)
                if quoted and qid not in included_ids:
                    by_conversation[conversation_id].append(quoted)
                    included_ids.add(qid)

    entries: list[dict[str, Any]] = []
    wanted_media_keys = {key for items in by_conversation.values() for item in items for key in media_keys(item)}
    emit_checkpoint(reporter, "MEDIA_DOWNLOAD_START", photos=len(wanted_media_keys))
    media_paths = download_photos(media, paths.media_dir, wanted_media_keys)
    emit_checkpoint(reporter, "MEDIA_DOWNLOAD_DONE", downloaded=len(media_paths), requested=len(wanted_media_keys))
    ignored_this_run = 0
    emit_checkpoint(reporter, "THREAD_RENDER_START", conversations=len(by_conversation), ai_enabled=False)
    for conversation_id, items in by_conversation.items():
        existing_record = find_cached_thread_record(paths.json_dir, conversation_id)
        existing_data = existing_record[1] if existing_record else {}
        local_media = thread_local_media(media, items)
        local_media_paths = thread_local_media_paths(media_paths, items)
        root_tweet = tweets.get(conversation_id)
        created_at = thread_created_at(root_tweet, items)
        title, slug = thread_title(root_tweet, items)
        op_tickers = root_post_tickers(root_tweet)
        metadata_tickers = root_primary_tickers(root_tweet)
        relevance_tickers = source_conversation_tickers(root_tweet, items, context)
        thread_type = classify_thread(root_tweet, items, context)
        tags = list(dict.fromkeys(infer_tags(items, thread_type, metadata_tickers, context) + media_placeholder_tags(items, local_media, context)))
        label = primary_label(metadata_tickers, tags)
        title = title_with_label_prefix(title, label)
        reason = ignore_reason(root_tweet, items, thread_type, relevance_tickers, context)
        if reason:
            ignored_this_run += 1
            emit_checkpoint(reporter, "THREAD_IGNORED", conversation_id=conversation_id, reason=reason)
            ignored_data = {
                "conversation_id": conversation_id,
                "title": title,
                "canonical_filename": existing_data.get("canonical_filename"),
                "type": thread_type,
                "primary_label": label,
                "tickers": metadata_tickers,
                **ticker_bucket_payload(op_tickers),
                "tags": tags,
                "tweets": items,
                "users": users,
                "media": local_media,
                "media_paths": local_media_paths,
                "non_photo_media": non_photo_media_placeholders(items, local_media, context),
                "source": context.source_record(kind="live_capture_or_cached_update", raw_api_used=True, x_api_called=True),
                "ignored": True,
                "ignored_reason": reason,
                "ignored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            if existing_record:
                existing_json_path, existing_json_data = existing_record
                existing_json_data.update(ignored_data)
                move_generated_json_to_ignored(paths.root, existing_json_path, paths.threads_dir, existing_json_data, reason, context)
            else:
                write_ignored_record(paths.root, conversation_id, reason, ignored_data, context)
                remove_thread_htmls(paths.threads_dir, conversation_id, ignored_data.get("canonical_filename"))
            continue
        tldr = rough_tldr(items, context.user_id)
        analysis = existing_data.get("analysis")
        analysis_metadata = base_thread_metadata(title, label, op_tickers, tags, tldr, existing_data)
        title = analysis_metadata["title"]
        label = analysis_metadata["primary_label"]
        tickers = analysis_metadata["tickers"]
        tags = analysis_metadata["tags"]
        tldr = analysis_metadata["tldr"]
        slug = safe_slug(title.split(" - ", 1)[-1] if " - " in title else title)
        prefix = date_prefix(root_tweet, items)
        filename = f"{prefix}__{label}__{slug}__{conversation_id}.html"
        html_path = paths.threads_dir / filename
        json_path = paths.json_dir / f"{prefix}__{label}__{slug}__{conversation_id}.json"
        is_cached = not options.force and conversation_id in cached_conversation_ids and not has_new_tweets(conversation_id)
        cached_record = existing_record if is_cached else None
        if cached_record:
            cached_json_path, cached_data = cached_record
            cached_filename = cached_data.get("canonical_filename")
            if cached_filename:
                json_path = cached_json_path
                html_path = paths.threads_dir / cached_filename
                filename = cached_filename
                title = cached_data.get("title", title)
                thread_type = cached_data.get("type", thread_type)
                label = cached_data.get("primary_label", label)
                tickers = cached_data.get("tickers", tickers)
                tags = cached_data.get("tags", tags)
                if analysis_metadata.get("analysis_ready"):
                    tldr = cached_data.get("tldr", tldr)
                    analysis_metadata.update(analysis_field_payload(cached_data))
        if is_cached and not html_path.exists():
            is_cached = False
        if not is_cached:
            cleanup_old_thread_versions(paths.json_dir, paths.threads_dir, conversation_id, json_path, html_path)
            render_thread_html(
                html_path,
                conversation_id,
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
                search_counts.get(conversation_id, 0),
                paths.root,
                context.username,
                context.user_id,
            )
        if not is_cached:
            json_path.write_text(
                json.dumps(
                    apply_pending_safe_summary(
                        {
                            "conversation_id": conversation_id,
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
                            "analysis_stage": existing_data.get("analysis_stage") or "captured_pending_ai_pass1",
                            "completeness_status": "conversation_search_partial",
                            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                            "tweets": items,
                            "users": users,
                            "media": local_media,
                            "media_paths": local_media_paths,
                            "non_photo_media": non_photo_media_placeholders(items, local_media, context),
                            "source": context.source_record(kind="live_capture", raw_api_used=True, x_api_called=True),
                            "rate_limits": client.rate_limits,
                        },
                        analysis_metadata,
                    ),
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        if is_cached:
            try:
                captured_at = json.loads(json_path.read_text(encoding="utf-8")).get(
                    "captured_at", dt.datetime.now(dt.timezone.utc).isoformat()
                )
            except Exception:
                captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
        else:
            captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
        entries.append(
            {
                "type": thread_type,
                "title": title,
                "date": f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}",
                "created_at": created_at,
                "captured_at": captured_at,
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
                "conversation_id": conversation_id,
                "abs_path": str(html_path),
                "posts": len(items),
                "source_posts": sum(1 for item in items if item.get("author_id") == context.user_id),
                "photos": sum(len(media_keys(item)) for item in items),
                **context.source_entry_fields(existing_data),
            }
        )

    emit_checkpoint(reporter, "THREAD_RENDER_DONE", rendered=len(entries), ignored=ignored_this_run, ai_enabled=False)

    processed_ids = {entry["conversation_id"] for entry in entries}
    entries.extend(
        entry for entry in entries_from_cached_json(paths.json_dir, paths.threads_dir, context) if entry["conversation_id"] not in processed_ids
    )

    render_all_indexes(paths.root, entries, load_owned_tickers())
    emit_checkpoint(reporter, "INDEX_RENDER_DONE", entries=len(entries), index=paths.root / "indexes" / "index.html")
    usage = write_usage_estimate(paths.root, run_id, client)
    return {
        "index": paths.root / "indexes" / "index.html",
        "threads": len(entries),
        "ignored": ignored_this_run,
        "raw_api_dir": paths.raw_dir,
        "media_dir": paths.media_dir,
        "api_calls": client.call_count,
        "unique_post_reads_estimate": usage["unique_post_ids_returned"],
        "estimated_x_cost_usd": usage["estimated_cost_usd"],
        "ai_in_capture": False,
    }
