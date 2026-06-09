"""Live X capture stage and X-specific maintenance helpers.

This module stops at clean local evidence: raw API, records, and still-image
media. Thread AI and vector sync intentionally live elsewhere.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_tool.runtime.paths import portable_path, resolve_portable_path, storage_paths_for_x_root
from investment_tool.runtime.reporting import JobReporter, report_event
from investment_tool.rules.filters import primary_label
from investment_tool.rules.tickers import ticker_bucket_payload
from investment_tool.feeds.x.context import XCaptureContext
from investment_tool.feeds.x.metadata import (
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
    feed_conversation_tickers,
    thread_created_at,
    thread_title,
    title_with_label_prefix,
)
from investment_tool.feeds.x.api import (
    ConversationSearchResult,
    XClient,
    download_photos,
    fetch_timeline,
    fetch_tweets_by_ids,
    fetch_tweets_by_ids_even_if_cached,
    photo_media_path,
    refresh_x_user_token,
    search_conversation,
)
from investment_tool.feeds.x.raw import load_raw_api_archive
from investment_tool.feeds.x.threads import (
    explicit_x_links,
    media_keys,
    parent_id,
    quoted_ids,
    referenced_ids,
    thread_local_media,
    thread_local_media_paths,
)
from investment_tool.presentation.threads import date_prefix
from investment_tool.feeds.x.store import (
    cleanup_old_json_versions,
    find_cached_thread_record,
    load_cached_threads,
    move_generated_json_to_ignored,
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
    incremental: bool = False


@dataclass(frozen=True)
class XCapturePaths:
    root: Path
    raw_dir: Path
    json_dir: Path
    media_dir: Path
    threads_dir: Path
    presentation_root: Path


@dataclass
class XCaptureState:
    client: XClient
    tweets: dict[str, dict]
    users: dict[str, dict]
    media: dict[str, dict]
    cached_tweet_ids: dict[str, set[str]]

    @property
    def cached_conversation_ids(self) -> set[str]:
        return set(self.cached_tweet_ids)


@dataclass
class XRecordWriteResult:
    entries: list[dict[str, Any]]
    ignored: int
    changed_conversation_ids: set[str]
    cached_conversation_ids: set[str]
    ignored_conversation_ids: set[str]


@dataclass
class XMediaDownloadResult:
    media_paths: dict[str, str]
    downloaded_media_keys: set[str]
    requested_media_keys: set[str]


def prepare_x_capture_paths(run_id: str, feed_root: str | Path | None = None) -> XCapturePaths:
    storage = storage_paths_for_x_root(feed_root)
    root = resolve_portable_path(feed_root) if feed_root else storage.x_root
    paths = XCapturePaths(
        root=root,
        raw_dir=root / "raw" / run_id,
        json_dir=root / "records",
        media_dir=root / "media",
        threads_dir=storage.x_thread_pages,
        presentation_root=storage.presentation_root,
    )
    for folder in (
        paths.raw_dir,
        paths.json_dir,
        paths.media_dir,
        paths.threads_dir,
        storage.indexes,
        root / "ignored",
        root / "rebuild",
        root / "backups",
        root / "usage",
    ):
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


def write_capture_manifest(
    root: Path,
    run_id: str,
    raw_dir: Path,
    entries: list[dict[str, Any]],
    discovered_conversation_ids: list[str],
    loaded_cached_conversation_ids: set[str],
    record_result: XRecordWriteResult,
    media_result: XMediaDownloadResult,
    description_candidate_media_keys: set[str],
    media_conversation_ids: dict[str, set[str]],
    usage: dict[str, Any],
    ignored: int,
) -> dict[str, Any]:
    usage_dir = root / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    all_conversation_ids = sorted(
        set(record_result.changed_conversation_ids)
        | set(record_result.cached_conversation_ids)
        | set(record_result.ignored_conversation_ids)
    )
    changed_conversation_ids = sorted(record_result.changed_conversation_ids)
    cached_conversation_ids = sorted(record_result.cached_conversation_ids)
    description_candidate_media_keys = set(description_candidate_media_keys)
    description_conversation_ids = {
        conversation_id
        for key in description_candidate_media_keys
        for conversation_id in media_conversation_ids.get(key, set())
    }
    render_conversation_ids = sorted(
        set(changed_conversation_ids)
        | set(record_result.ignored_conversation_ids)
        | description_conversation_ids
    )
    record = {
        "run_id": run_id,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "raw_api_dir": portable_path(raw_dir),
        "threads": len(entries),
        "ignored": ignored,
        "conversation_ids": sorted(str(entry.get("conversation_id") or "") for entry in entries if entry.get("conversation_id")),
        "discovered_conversation_ids": sorted(discovered_conversation_ids),
        "loaded_cached_conversation_ids": sorted(loaded_cached_conversation_ids),
        "loaded_cached_conversations": len(loaded_cached_conversation_ids),
        "all_conversation_ids": all_conversation_ids,
        "changed_conversation_ids": changed_conversation_ids,
        "cached_conversation_ids": cached_conversation_ids,
        "ignored_conversation_ids": sorted(record_result.ignored_conversation_ids),
        "render_conversation_ids": render_conversation_ids,
        "requested_media_keys": sorted(media_result.requested_media_keys),
        "downloaded_media_keys": sorted(media_result.downloaded_media_keys),
        "description_media_keys": sorted(description_candidate_media_keys),
        "description_candidate_media_keys": sorted(description_candidate_media_keys),
        "media_conversation_ids": {key: sorted(value) for key, value in sorted(media_conversation_ids.items())},
        "media_paths": {key: media_result.media_paths[key] for key in sorted(media_result.media_paths)},
        "api_calls": usage.get("api_calls"),
        "unique_post_reads_estimate": usage.get("unique_post_ids_returned"),
        "estimated_x_cost_usd": usage.get("estimated_cost_usd"),
    }
    with (usage_dir / "capture_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (usage_dir / "latest_capture_manifest.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def missing_media_metadata_targets(json_dir: Path, raw_media: dict[str, dict]) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = defaultdict(set)
    for json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            report_event(
                "WARNING",
                "x-capture",
                reason="json_read_failed",
                action="missing_media_metadata_targets",
                path=portable_path(json_path),
                error=str(exc),
            )
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
    json_dir = root / "records"
    media_dir = root / "media"
    tweets, users, media, raw_stats = load_raw_api_archive(root / "raw")
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


def initialize_capture_state(paths: XCapturePaths, env_path: Path, token: str) -> XCaptureState:
    client = XClient(token, paths.raw_dir, refresh_callback=lambda: refresh_x_user_token(env_path))
    tweets: dict[str, dict] = {}
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}
    cached_tweet_ids = load_cached_threads(paths.json_dir, tweets, users, media)
    if cached_tweet_ids:
        print(f"CACHED={len(cached_tweet_ids)} threads found locally")
    return XCaptureState(client, tweets, users, media, cached_tweet_ids)


def fetch_seed_context(
    state: XCaptureState,
    options: XCaptureOptions,
    context: XCaptureContext,
    reporter: JobReporter | None,
) -> list[str]:
    emit_checkpoint(reporter, "X_TIMELINE_FETCH_START", pages=options.timeline_pages)
    known_tweet_ids = set(state.tweets)
    stop_after_known_streak = min(20, max(1, options.max_threads)) if options.incremental and not options.force else 0
    seed_ids = fetch_timeline(
        state.client,
        context.user_id,
        options.timeline_pages,
        state.tweets,
        state.users,
        state.media,
        known_tweet_ids=known_tweet_ids if options.incremental and not options.force else None,
        stop_after_known_streak=stop_after_known_streak,
    )
    emit_checkpoint(
        reporter,
        "X_TIMELINE_FETCH_DONE",
        seed_posts=len(seed_ids),
        total_posts=len(state.tweets),
        api_calls=state.client.call_count,
    )
    if options.conversation_id:
        seed_ids.append(options.conversation_id)
        fetch_tweets_by_ids(
            state.client,
            [options.conversation_id],
            state.tweets,
            state.users,
            state.media,
            "requested_conversation",
        )
        emit_checkpoint(
            reporter,
            "X_REQUESTED_CONVERSATION_FETCH_DONE",
            conversation_id=options.conversation_id,
            api_calls=state.client.call_count,
        )
    if options.incremental and not options.force and not options.conversation_id:
        context_seed_ids = [tweet_id for tweet_id in seed_ids if tweet_id not in known_tweet_ids]
    else:
        context_seed_ids = seed_ids
    emit_checkpoint(reporter, "X_CONTEXT_WALK_START", seed_posts=len(context_seed_ids), incremental=options.incremental)
    walk_context(state.client, context_seed_ids, state.tweets, state.users, state.media)
    emit_checkpoint(
        reporter,
        "X_CONTEXT_WALK_DONE",
        total_posts=len(state.tweets),
        users=len(state.users),
        media=len(state.media),
        api_calls=state.client.call_count,
    )
    return seed_ids


def discover_conversation_ids(
    tweets: dict[str, dict],
    options: XCaptureOptions,
    context: XCaptureContext,
    seed_ids: list[str] | None = None,
    cached_tweet_ids: dict[str, set[str]] | None = None,
) -> list[str]:
    if options.conversation_id:
        return [options.conversation_id]
    if options.incremental and seed_ids is not None and not options.force:
        cached_tweet_ids = cached_tweet_ids or {}
        conversation_ids: list[str] = []
        for tweet_id in seed_ids:
            tweet = tweets.get(tweet_id) or {}
            if tweet.get("author_id") != context.user_id:
                continue
            conv = tweet.get("conversation_id")
            if not conv:
                continue
            if tweet_id in cached_tweet_ids.get(conv, set()):
                continue
            if conv not in conversation_ids:
                conversation_ids.append(conv)
            if len(conversation_ids) >= options.max_threads:
                break
        return conversation_ids
    conversation_ids: list[str] = []
    for tweet in sorted(tweets.values(), key=lambda item: item.get("created_at") or "", reverse=True):
        if tweet.get("author_id") != context.user_id:
            continue
        conv = tweet.get("conversation_id")
        if conv and conv not in conversation_ids:
            conversation_ids.append(conv)
        if len(conversation_ids) >= options.max_threads:
            break
    return conversation_ids


def has_new_tweets(conv_id: str, tweets: dict[str, dict], cached_tweet_ids: dict[str, set[str]]) -> bool:
    known = cached_tweet_ids.get(conv_id, set())
    current = {tid for tid, tweet in tweets.items() if tweet.get("conversation_id") == conv_id}
    return bool(current - known)


def cached_conversation_needs_search(json_dir: Path, conversation_id: str) -> bool:
    cached_record = find_cached_thread_record(json_dir, conversation_id)
    if not cached_record:
        return True
    source_completeness = cached_record[1].get("source_completeness") or {}
    conversation_search = source_completeness.get("conversation_search") or {}
    return conversation_search.get("has_more") is True


def search_selected_conversations(
    paths: XCapturePaths,
    state: XCaptureState,
    conversation_ids: list[str],
    options: XCaptureOptions,
    reporter: JobReporter | None,
) -> dict[str, ConversationSearchResult]:
    search_results: dict[str, ConversationSearchResult] = {}
    conversation_search_run = 0
    conversation_search_skipped = 0
    for conversation_id in conversation_ids:
        if (
            not options.force
            and conversation_id in state.cached_conversation_ids
            and not has_new_tweets(conversation_id, state.tweets, state.cached_tweet_ids)
            and not cached_conversation_needs_search(paths.json_dir, conversation_id)
        ):
            conversation_search_skipped += 1
            continue
        conversation_search_run += 1
        emit_checkpoint(reporter, "X_CONVERSATION_SEARCH_START", conversation_id=conversation_id, pages=options.conversation_pages)
        search_results[conversation_id] = search_conversation(
            state.client,
            conversation_id,
            state.tweets,
            state.users,
            state.media,
            options.conversation_pages,
        )
        conv_ids = [tweet_id for tweet_id, tweet in state.tweets.items() if tweet.get("conversation_id") == conversation_id]
        walk_context(state.client, conv_ids, state.tweets, state.users, state.media)
        emit_checkpoint(
            reporter,
            "X_CONVERSATION_SEARCH_DONE",
            conversation_id=conversation_id,
            search_results=search_results[conversation_id].result_count,
            pages_fetched=search_results[conversation_id].pages_fetched,
            has_more=search_results[conversation_id].has_more,
            missing_references=len(search_results[conversation_id].missing_reference_ids),
            conversation_posts=len(conv_ids),
            api_calls=state.client.call_count,
        )
    emit_checkpoint(
        reporter,
        "X_CONVERSATION_SEARCH_SUMMARY",
        searched=conversation_search_run,
        skipped_cached=conversation_search_skipped,
    )
    return search_results


def source_completeness_payload(
    conversation_id: str,
    root_tweet: dict | None,
    items: list[dict],
    all_tweets: dict[str, dict],
    search_result: ConversationSearchResult | None,
) -> dict[str, Any]:
    missing_reference_ids = {
        ref_id
        for item in items
        for ref_id in referenced_ids(item)
        if ref_id and ref_id not in all_tweets
    }
    if search_result:
        missing_reference_ids.update(search_result.missing_reference_ids)
    root_present = bool(root_tweet)
    if search_result and search_result.has_more:
        status = "conversation_search_limited"
    elif not root_present or missing_reference_ids:
        status = "api_partial_missing_references"
    elif search_result:
        status = "conversation_search_exhausted"
    else:
        status = "not_searched_cached"
    payload: dict[str, Any] = {
        "status": status,
        "root_tweet_present": root_present,
        "missing_root_tweet": not root_present,
        "missing_reference_ids": sorted(missing_reference_ids),
    }
    if search_result:
        payload["conversation_search"] = {
            "result_count": search_result.result_count,
            "pages_requested": search_result.pages_requested,
            "pages_fetched": search_result.pages_fetched,
            "has_more": search_result.has_more,
            "error_count": search_result.error_count,
        }
    return payload


def assemble_conversations(
    tweets: dict[str, dict],
    conversation_ids: list[str],
    context: XCaptureContext,
) -> dict[str, list[dict]]:
    by_conversation: dict[str, list[dict]] = {conversation_id: [] for conversation_id in conversation_ids}
    for tweet in tweets.values():
        conv = tweet.get("conversation_id")
        if conv in by_conversation:
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
    return by_conversation


def download_conversation_media(
    paths: XCapturePaths,
    conversations: dict[str, list[dict]],
    media: dict[str, dict],
    reporter: JobReporter | None,
) -> XMediaDownloadResult:
    wanted_media_keys = {key for items in conversations.values() for item in items for key in media_keys(item)}
    preexisting = {
        key
        for key in wanted_media_keys
        if key in media
        and (media.get(key) or {}).get("type") == "photo"
        and (media.get(key) or {}).get("url")
        and photo_media_path(paths.media_dir, key, media[key]).exists()
    }
    emit_checkpoint(reporter, "MEDIA_DOWNLOAD_START", photos=len(wanted_media_keys))
    media_paths = download_photos(media, paths.media_dir, wanted_media_keys)
    downloaded_media_keys = set(media_paths) - preexisting
    emit_checkpoint(
        reporter,
        "MEDIA_DOWNLOAD_DONE",
        downloaded=len(downloaded_media_keys),
        local=len(media_paths),
        requested=len(wanted_media_keys),
    )
    return XMediaDownloadResult(media_paths, downloaded_media_keys, wanted_media_keys)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def media_needs_description(media_key: str, media_path_text: str, descriptions_dir: Path) -> bool:
    media_path = resolve_portable_path(media_path_text)
    out_path = descriptions_dir / f"{media_key}.json"
    if not media_path.exists():
        return False
    if not out_path.exists():
        return True
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception:
        return True
    return data.get("file_sha256") != file_sha256(media_path) or not data.get("analysis")


def description_candidates_for_media(media_paths: dict[str, str], descriptions_dir: Path) -> set[str]:
    return {
        key
        for key, media_path in media_paths.items()
        if media_needs_description(key, media_path, descriptions_dir)
    }


def media_conversation_map(conversations: dict[str, list[dict]]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for conversation_id, items in conversations.items():
        for item in items:
            for key in media_keys(item):
                mapping[key].add(conversation_id)
    return mapping


def write_conversation_records(
    paths: XCapturePaths,
    state: XCaptureState,
    conversations: dict[str, list[dict]],
    search_results: dict[str, ConversationSearchResult],
    options: XCaptureOptions,
    context: XCaptureContext,
    media_paths: dict[str, str],
    reporter: JobReporter | None,
) -> XRecordWriteResult:
    entries: list[dict[str, Any]] = []
    ignored_this_run = 0
    changed_conversation_ids: set[str] = set()
    cached_conversation_ids: set[str] = set()
    ignored_conversation_ids: set[str] = set()
    emit_checkpoint(reporter, "THREAD_RECORD_WRITE_START", conversations=len(conversations), ai_enabled=False)
    for conversation_id, items in conversations.items():
        existing_record = find_cached_thread_record(paths.json_dir, conversation_id)
        existing_data = existing_record[1] if existing_record else {}
        local_media = thread_local_media(state.media, items)
        local_media_paths = thread_local_media_paths(media_paths, items)
        root_tweet = state.tweets.get(conversation_id)
        source_completeness = source_completeness_payload(
            conversation_id,
            root_tweet,
            items,
            state.tweets,
            search_results.get(conversation_id),
        )
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
            ignored_this_run += 1
            ignored_conversation_ids.add(conversation_id)
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
                "users": state.users,
                "media": local_media,
                "media_paths": local_media_paths,
                "non_photo_media": non_photo_media_placeholders(items, local_media, context),
                "source_completeness": source_completeness,
                "completeness_status": source_completeness["status"],
                "feed": context.feed_record(kind="live_capture_or_cached_update", raw_api_used=True, x_api_called=True),
                "ignored": True,
                "ignored_reason": reason,
                "ignored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            if existing_record:
                existing_json_path, existing_json_data = existing_record
                existing_json_data.update(ignored_data)
                move_generated_json_to_ignored(
                    paths.root,
                    existing_json_path,
                    paths.threads_dir,
                    existing_json_data,
                    reason,
                    context,
                    remove_html=True,
                )
            else:
                write_ignored_record(paths.root, conversation_id, reason, ignored_data, context)
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
        is_cached = (
            not options.force
            and conversation_id in state.cached_conversation_ids
            and not has_new_tweets(conversation_id, state.tweets, state.cached_tweet_ids)
        )
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
        if not is_cached:
            changed_conversation_ids.add(conversation_id)
            cleanup_old_json_versions(paths.json_dir, conversation_id, json_path)
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
                            "source_completeness": source_completeness,
                            "completeness_status": source_completeness["status"],
                            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                            "tweets": items,
                            "users": state.users,
                            "media": local_media,
                            "media_paths": local_media_paths,
                            "non_photo_media": non_photo_media_placeholders(items, local_media, context),
                            "feed": context.feed_record(kind="live_capture", raw_api_used=True, x_api_called=True),
                            "rate_limits": state.client.rate_limits,
                        },
                        analysis_metadata,
                    ),
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        if is_cached:
            cached_conversation_ids.add(conversation_id)
            try:
                captured_at = json.loads(json_path.read_text(encoding="utf-8")).get(
                    "captured_at", dt.datetime.now(dt.timezone.utc).isoformat()
                )
            except Exception as exc:
                report_event(
                    "WARNING",
                    "x-capture",
                    reason="json_read_failed",
                    action="cached_capture_timestamp",
                    path=portable_path(json_path),
                    error=str(exc),
                )
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
                "feed_posts": sum(1 for item in items if item.get("author_id") == context.user_id),
                "photos": sum(len(media_keys(item)) for item in items),
                **context.feed_entry_fields(existing_data),
            }
        )
    emit_checkpoint(reporter, "THREAD_RECORD_WRITE_DONE", records=len(entries), ignored=ignored_this_run, ai_enabled=False)
    return XRecordWriteResult(entries, ignored_this_run, changed_conversation_ids, cached_conversation_ids, ignored_conversation_ids)


def run_live_x_capture(
    paths: XCapturePaths,
    run_id: str,
    env_path: Path,
    token: str,
    options: XCaptureOptions,
    context: XCaptureContext,
    reporter: JobReporter | None = None,
) -> dict[str, Any]:
    state = initialize_capture_state(paths, env_path, token)
    seed_ids = fetch_seed_context(state, options, context, reporter)
    conversation_ids = discover_conversation_ids(state.tweets, options, context, seed_ids, state.cached_tweet_ids)
    emit_checkpoint(reporter, "THREAD_DISCOVERY_DONE", conversations=len(conversation_ids), cached=len(state.cached_conversation_ids))
    search_results = search_selected_conversations(paths, state, conversation_ids, options, reporter)
    conversations = assemble_conversations(state.tweets, conversation_ids, context)
    media_result = download_conversation_media(paths, conversations, state.media, reporter)
    record_result = write_conversation_records(
        paths,
        state,
        conversations,
        search_results,
        options,
        context,
        media_result.media_paths,
        reporter,
    )
    storage = storage_paths_for_x_root(paths.root)
    description_candidate_media_keys = description_candidates_for_media(media_result.media_paths, storage.x_descriptions)
    media_conversation_ids = media_conversation_map(conversations)
    usage = write_usage_estimate(paths.root, run_id, state.client)
    capture_manifest = write_capture_manifest(
        paths.root,
        run_id,
        paths.raw_dir,
        record_result.entries,
        conversation_ids,
        state.cached_conversation_ids,
        record_result,
        media_result,
        description_candidate_media_keys,
        media_conversation_ids,
        usage,
        record_result.ignored,
    )
    return {
        "threads": len(record_result.entries),
        "ignored": record_result.ignored,
        "raw_api_dir": portable_path(paths.raw_dir),
        "records_dir": portable_path(paths.json_dir),
        "media_dir": portable_path(paths.media_dir),
        "description_media_keys": capture_manifest["description_media_keys"],
        "changed_conversation_ids": capture_manifest["changed_conversation_ids"],
        "cached_conversation_ids": capture_manifest["cached_conversation_ids"],
        "render_conversation_ids": capture_manifest["render_conversation_ids"],
        "api_calls": state.client.call_count,
        "unique_post_reads_estimate": usage["unique_post_ids_returned"],
        "estimated_x_cost_usd": usage["estimated_cost_usd"],
        "ai_in_capture": False,
    }
