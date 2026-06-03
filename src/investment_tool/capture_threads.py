"""Compatibility wrapper for the X capture stage.

The production workflow now lives in ``pipeline_orchestrator`` and the X-stage
implementation lives in focused ``x_*`` modules. This module preserves the old
entrypoint and selected helper imports while callers migrate.
"""

from __future__ import annotations

from typing import Sequence

from investment_tool.pipeline_orchestrator import main_legacy_x_capture
from investment_tool.x_capture_context import load_x_capture_context
from investment_tool.x_capture_job import (
    XCaptureOptions,
    XCapturePaths,
    data_root,
    missing_media_metadata_targets,
    prepare_x_capture_paths,
    recover_missing_media_metadata,
    run_live_x_capture,
    walk_context,
    write_usage_estimate,
)
from investment_tool.x_capture_metadata import (
    analysis_field_payload,
    apply_pending_safe_summary,
    base_thread_metadata,
    classify_thread as _classify_thread,
    compact_text,
    ignore_reason as _ignore_reason,
    infer_tags as _infer_tags,
    investment_relevance_score as _investment_relevance_score,
    media_placeholder_tags as _media_placeholder_tags,
    non_photo_media_placeholders as _non_photo_media_placeholders,
    relevance_text as _relevance_text,
    root_post_tickers,
    root_primary_tickers,
    rough_tldr as _rough_tldr,
    safe_slug,
    source_conversation_tickers as _source_conversation_tickers,
    thread_created_at,
    thread_title,
    title_with_label_prefix,
)
from investment_tool.x_raw_archive import load_raw_api_archive, raw_response_tweets, saved_raw_response
from investment_tool.x_raw_rebuild import (
    clean_raw_rebuilt_thread_record,
    conversation_ids_from_raw_tweets,
    group_raw_conversations,
    rebuild_from_raw_api,
    replace_generated_thread_jsons,
)
from investment_tool.x_thread_model import (
    display_text,
    existing_local_media_paths,
    explicit_x_links,
    media_keys,
    missing_media_keys,
    parent_id,
    quoted_ids,
    referenced_ids,
    thread_local_media,
    thread_local_media_paths,
    thread_media_keys,
    thread_user_map,
)
from investment_tool.x_thread_store import (
    apply_cached_relevance_gate,
    cleanup_old_thread_versions,
    entries_from_cached_json,
    find_cached_thread_record,
    load_cached_threads,
    load_owned_tickers,
    move_generated_json_to_ignored,
    remove_thread_htmls,
    render_cached_indexes,
    repair_cached_media_paths,
    rerender_cached_threads,
    write_ignored_record,
)


_DEFAULT_CONTEXT = load_x_capture_context()


def non_photo_media_placeholders(items: list[dict], media: dict[str, dict]) -> list[dict]:
    return _non_photo_media_placeholders(items, media, _DEFAULT_CONTEXT)


def media_placeholder_tags(items: list[dict], media: dict[str, dict]) -> list[str]:
    return _media_placeholder_tags(items, media, _DEFAULT_CONTEXT)


def relevance_text(root: dict | None, items: list[dict]) -> str:
    return _relevance_text(root, items, _DEFAULT_CONTEXT)


def investment_relevance_score(root: dict | None, items: list[dict], tickers: list[str]) -> int:
    return _investment_relevance_score(root, items, tickers, _DEFAULT_CONTEXT)


def ignore_reason(root: dict | None, items: list[dict], thread_type: str, tickers: list[str]) -> str | None:
    return _ignore_reason(root, items, thread_type, tickers, _DEFAULT_CONTEXT)


def infer_tags(items: list[dict], thread_type: str, tickers: list[str]) -> list[str]:
    return _infer_tags(items, thread_type, tickers, _DEFAULT_CONTEXT)


def rough_tldr(items: list[dict]) -> str:
    return _rough_tldr(items, _DEFAULT_CONTEXT.user_id)


def classify_thread(root: dict | None, items: list[dict]) -> str:
    return _classify_thread(root, items, _DEFAULT_CONTEXT)


def source_conversation_tickers(root: dict | None, items: list[dict]) -> list[str]:
    return _source_conversation_tickers(root, items, _DEFAULT_CONTEXT)


def main(argv: Sequence[str] | None = None) -> int:
    return main_legacy_x_capture(argv)


if __name__ == "__main__":
    raise SystemExit(main())
