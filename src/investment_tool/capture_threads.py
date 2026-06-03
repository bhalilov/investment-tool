"""Capture configured X source threads, media, raw API responses, JSON snapshots, and HTML reports."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from investment_tool.runtime import load_env
from investment_tool.reporting import JobReporter, start_reporter
from investment_tool.index_render import render_all_indexes
from investment_tool.source_config import SourceProfile, load_source_rules, load_x_source_profile, source_identity, source_label
from investment_tool.thread_filtering import (
    ThreadFilterConfig,
    ignore_reason as generic_ignore_reason,
    infer_tags as generic_infer_tags,
    investment_relevance_score as generic_investment_relevance_score,
    primary_label,
    relevance_text as generic_relevance_text,
)
from investment_tool.ticker_parser import (
    TICKER_ALIASES,
    extract_tickers,
    normalize_ticker as normalize_thread_ticker,
    ticker_bucket_payload,
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
from investment_tool.x_raw_archive import load_raw_api_archive, raw_response_tweets, saved_raw_response
from investment_tool.x_thread_model import (
    display_text,
    existing_local_media_paths,
    explicit_x_links,
    media_keys,
    missing_media_keys,
    non_photo_media_placeholders as model_non_photo_media_placeholders,
    parent_id,
    quoted_ids,
    referenced_ids,
    thread_local_media,
    thread_local_media_paths,
    thread_media_keys,
    thread_user_map,
    media_placeholder_tags as model_media_placeholder_tags,
)
from investment_tool.x_thread_render import date_prefix, render_thread_html


SOURCE_PROFILE: SourceProfile = load_x_source_profile()
SOURCE_USERNAME = SOURCE_PROFILE.username
SOURCE_USER_ID = SOURCE_PROFILE.user_id
SOURCE_DISPLAY_NAME = SOURCE_PROFILE.display_name
SOURCE_THREAD_RULES, SOURCE_MEDIA_RULES = load_source_rules(SOURCE_PROFILE)

STOPWORDS = {
    "about",
    "after",
    "again",
    "already",
    "answer",
    "because",
    "before",
    "being",
    "channel",
    "continue",
    "could",
    "current",
    "every",
    "first",
    "from",
    "have",
    "here",
    "receive",
    "into",
    "just",
    "late",
    "like",
    "more",
    "much",
    "question",
    "questions",
    "same",
    "should",
    "still",
    "that",
    "their",
    "there",
    "this",
    "through",
    "when",
    "where",
    "will",
    "with",
    "would",
}
SIGNAL_VALUES = {"BUY_SIGNAL", "SELL_SIGNAL", "TRIM_SIGNAL", "HOLD_SIGNAL", "AVOID_SIGNAL", "WATCH_SIGNAL", "NO_ACTION"}
CATEGORY_VALUES = {
    "TRADE_ALERT",
    "THESIS_UPDATE",
    "VALUATION",
    "PORTFOLIO_UPDATE",
    "RISK_WARNING",
    "MACRO",
    "QUESTION_REPLY",
    "RANT",
    "BRAG",
    "SELF_PROMO",
    "OFF_TOPIC",
}
STANCE_VALUES = {"BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNCLEAR"}
TIME_HORIZON_VALUES = {"IMMEDIATE", "DAYS", "WEEKS", "MONTHS", "YEARS", "UNCLEAR"}
PRIORITY_VALUES = {"P0", "P1", "P2", "P3", "P4"}
SCREENSHOT_IMPORTANCE_VALUES = {"NONE", "LOW", "IMPORTANT", "CRITICAL"}
TONE_VALUES = {"LITERAL", "SARCASTIC", "MOCKING", "QUOTING_OTHER_VIEW", "UNCLEAR"}
REPORTER: JobReporter | None = None
ANALYSIS_TOP_LEVEL_FIELDS = [
    "primary_ticker",
    "context_tickers",
    "mentioned_only_tickers",
    "signal",
    "category",
    "stance",
    "time_horizon",
    "tone",
    "priority",
    "actionability_score",
    "confidence",
    "screenshot_importance",
    "ocr_needed",
    "linked_context_required",
    "evidence",
    "ambiguities",
    "contradiction_flags",
    "flags",
]
DEFAULT_X_POST_READ_COST_USD = 0.005
DEFAULT_OWNED_POSITIONS_FILE = Path("config/owned_positions.json")


def load_cached_threads(
    json_dir: Path,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
) -> dict[str, set[str]]:
    """Load all previously captured thread JSONs into the in-memory dicts.

    Returns a mapping of conversation_id -> set of tweet IDs that were in the
    cache, so the caller can detect whether new replies have arrived since the
    last capture.
    """
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


def data_root() -> Path:
    return Path(os.environ.get("INVESTMENT_TOOL_DATA_DIR", "~/investment-tool-data")).expanduser()


def load_owned_tickers() -> set[str]:
    configured = os.environ.get("OWNED_POSITIONS_FILE", "").strip()
    path = Path(configured).expanduser() if configured else Path.cwd() / DEFAULT_OWNED_POSITIONS_FILE
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


def safe_slug(value: str, fallback: str = "thread") -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:90] or fallback


def compact_text(value: str, limit: int = 1800) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] + ("..." if len(value) > limit else "")


def non_photo_media_placeholders(items: list[dict], media: dict[str, dict]) -> list[dict[str, Any]]:
    return model_non_photo_media_placeholders(items, media, SOURCE_MEDIA_RULES)


def media_placeholder_tags(items: list[dict], media: dict[str, dict]) -> list[str]:
    return model_media_placeholder_tags(items, media, SOURCE_MEDIA_RULES)


def configured_thread_label(name: str, fallback: str) -> str:
    labels = SOURCE_THREAD_RULES.get("thread_type_labels") or {}
    return str(labels.get(name) or fallback)


def x_source_record(**capture_fields: Any) -> dict[str, Any]:
    return {
        **source_identity(SOURCE_PROFILE),
        **{key: value for key, value in capture_fields.items() if value is not None},
    }


def source_entry_fields(data: dict[str, Any] | None = None) -> dict[str, str]:
    source = (data or {}).get("source") or {}
    username = str(source.get("username") or SOURCE_USERNAME).lstrip("@")
    display_name = str(source.get("display_name") or SOURCE_DISPLAY_NAME or username)
    if username:
        display = f"{display_name} (@{username})" if display_name and display_name != username else f"@{username}"
    else:
        display = source_label(SOURCE_PROFILE)
    return {
        "source_display": display,
        "source_label": display,
        "source_platform": str(source.get("platform") or SOURCE_PROFILE.platform),
        "source_id": str(source.get("source_id") or SOURCE_PROFILE.source_id),
    }


def thread_filter_config() -> ThreadFilterConfig:
    return ThreadFilterConfig(
        source_user_id=SOURCE_USER_ID,
        source_started_label=configured_thread_label("source_started_thread", "SOURCE_THREAD"),
        source_reply_label=configured_thread_label("source_reply_context", "SOURCE_REPLY_CONTEXT"),
        linked_context_domains=tuple(str(item).lower() for item in SOURCE_PROFILE.user_specifics.get("linked_context_domains") or []),
        self_promo_patterns=tuple(str(item) for item in SOURCE_THREAD_RULES.get("self_promo_patterns") or []),
    )


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


def root_post_tickers(root: dict | None) -> list[str]:
    return extract_tickers(display_text(root or {}))


def root_primary_tickers(root: dict | None) -> list[str]:
    tickers = root_post_tickers(root)
    return tickers if len(tickers) == 1 else []


def source_conversation_tickers(root: dict | None, items: list[dict]) -> list[str]:
    source_items = [item for item in items if item.get("author_id") == SOURCE_USER_ID]
    ticker_text = " ".join([display_text(root or {})] + [display_text(item) for item in source_items])
    return extract_tickers(ticker_text)


def thread_title(root: dict | None, items: list[dict]) -> tuple[str, str]:
    source = root or (items[0] if items else {})
    text = display_text(source)
    tickers = root_primary_tickers(source)
    topic = topic_phrase(text)
    prefix = "/".join(tickers[:3]) if tickers else "X"
    title = f"{prefix} - {topic}"
    return title, safe_slug(topic)


def topic_phrase(text: str) -> str:
    cleaned = html.unescape(re.sub(r"https?://\S+", "", text)).strip()
    first_para = cleaned.split("\n\n", 1)[0].strip()
    if ":" in first_para:
        before, after = first_para.split(":", 1)
        company = next((name.title() for name in TICKER_ALIASES if name.lower() == name and re.search(rf"\b{name}\b", before, re.I)), "")
        after = after.strip(" -")
        if company and after:
            return f"{company}: {after[:90]}".strip()
    match = re.search(r"(.{20,180}?[?.!])(?:\s|$)", first_para)
    phrase = (match.group(1) if match else first_para[:120]).strip()
    words = phrase.split()
    return " ".join(words[:14]) if words else "X thread"


def title_with_label_prefix(title: str, label: str) -> str:
    if title.startswith("X - ") and label not in {"", "UNKNOWN"}:
        return f"{label} - {title[4:]}"
    return title


def is_retweet(tweet: dict | None) -> bool:
    return any(ref.get("type") == "retweeted" for ref in (tweet or {}).get("referenced_tweets") or [])


def relevance_text(root: dict | None, items: list[dict]) -> str:
    return generic_relevance_text(root, items, SOURCE_USER_ID, display_text)


def investment_relevance_score(root: dict | None, items: list[dict], tickers: list[str]) -> int:
    return generic_investment_relevance_score(
        root,
        items,
        tickers,
        thread_filter_config(),
        display_text,
        explicit_x_links,
        media_keys,
    )


def ignore_reason(root: dict | None, items: list[dict], thread_type: str, tickers: list[str]) -> str | None:
    return generic_ignore_reason(
        root,
        items,
        thread_type,
        tickers,
        thread_filter_config(),
        display_text,
        is_retweet,
        explicit_x_links,
        media_keys,
    )


def write_ignored_record(root: Path, conversation_id: str, reason: str, data: dict) -> None:
    ignored_dir = root / "ignored"
    ignored_dir.mkdir(parents=True, exist_ok=True)
    tweets = data.get("tweets") or []
    source_posts = [tweet for tweet in tweets if tweet.get("author_id") == SOURCE_USER_ID]
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
        "source_posts": len(source_posts),
        "root_author_id": (root_tweet or {}).get("author_id"),
        "sample_text": compact_text(display_text(source_posts[0] if source_posts else root_tweet or {}), 500),
        "source": x_source_record(kind="ignored_thread_record"),
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
) -> None:
    conversation_id = str(data.get("conversation_id") or json_path.stem.rsplit("__", 1)[-1])
    data["ignored"] = True
    data["ignored_reason"] = reason
    data["ignored_at"] = data.get("ignored_at") or dt.datetime.now(dt.timezone.utc).isoformat()
    write_ignored_record(root, conversation_id, reason, data)
    remove_thread_htmls(threads_dir, conversation_id, data.get("canonical_filename"))
    json_path.unlink(missing_ok=True)


def normalize_enum(value: str | None, allowed: set[str], fallback: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")
    return normalized if normalized in allowed else fallback


def clamp_score(value: object) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def text_list(value: object, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = compact_text(str(item).strip(), 220)
        if text:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def base_thread_metadata(
    title: str,
    label: str,
    tickers: list[str],
    tags: list[str],
    tldr: str,
    existing: dict | None = None,
) -> dict[str, Any]:
    """Return display/index metadata without running AI.

    Capture owns collection and readable rendering only. Existing analysis fields
    are preserved for backward-compatible indexes, but new final judgments are
    produced by the separate AI pass pipeline.
    """
    existing = existing if isinstance(existing, dict) else {}
    analysis_stage = str(existing.get("analysis_stage") or "captured_pending_ai_pass1")
    analysis_ready = bool(existing.get("analysis")) and "pending" not in analysis_stage.lower()
    op_tickers = [normalize_thread_ticker(ticker) for ticker in tickers]
    op_tickers = [ticker for ticker in op_tickers if ticker != "UNKNOWN"]
    op_tickers = list(dict.fromkeys(op_tickers))
    primary = op_tickers[0] if len(op_tickers) == 1 else "UNKNOWN"
    mentioned_only = op_tickers if len(op_tickers) > 1 else []
    normalized_tickers = [primary] if primary != "UNKNOWN" else []
    normalized_label = primary if primary != "UNKNOWN" else label
    if normalized_label == "UNKNOWN":
        normalized_label = label
    category = normalize_enum(existing.get("category"), CATEGORY_VALUES, "") if analysis_ready else ""
    flags = text_list(existing.get("flags"), 12) if analysis_ready else []
    preview_text = compact_text(str(existing.get("preview_text") or existing.get("capture_preview") or existing.get("tldr") or tldr), 420)
    return {
        "title": compact_text(str(title), 120),
        "primary_label": normalized_label,
        "tickers": normalized_tickers,
        "tags": list(dict.fromkeys(tags + ([category] if category else []))),
        "tldr": compact_text(str(existing.get("tldr") or tldr), 420) if analysis_ready else "",
        "preview_text": "" if analysis_ready else preview_text,
        "summary_label": "TLDR" if analysis_ready else "Preview",
        "analysis_stage": analysis_stage,
        "analysis_ready": analysis_ready,
        "primary_ticker": primary,
        "context_tickers": [],
        "mentioned_only_tickers": list(dict.fromkeys(mentioned_only)),
        "signal": normalize_enum(existing.get("signal"), SIGNAL_VALUES, "") if analysis_ready else "",
        "category": category,
        "stance": normalize_enum(existing.get("stance"), STANCE_VALUES, "") if analysis_ready else "",
        "time_horizon": normalize_enum(existing.get("time_horizon"), TIME_HORIZON_VALUES, "") if analysis_ready else "",
        "tone": normalize_enum(existing.get("tone"), TONE_VALUES, "") if analysis_ready else "",
        "priority": normalize_enum(existing.get("priority"), PRIORITY_VALUES, "") if analysis_ready else "",
        "actionability_score": clamp_score(existing.get("actionability_score")) if analysis_ready else None,
        "confidence": clamp_score(existing.get("confidence")) if analysis_ready else None,
        "screenshot_importance": (
            normalize_enum(existing.get("screenshot_importance"), SCREENSHOT_IMPORTANCE_VALUES, "") if analysis_ready else ""
        ),
        "ocr_needed": bool(existing.get("ocr_needed", False)) if analysis_ready else None,
        "linked_context_required": bool(existing.get("linked_context_required", False)) if analysis_ready else None,
        "evidence": text_list(existing.get("evidence"), 8) if analysis_ready else [],
        "ambiguities": text_list(existing.get("ambiguities"), 8) if analysis_ready else [],
        "contradiction_flags": text_list(existing.get("contradiction_flags"), 8) if analysis_ready else [],
        "flags": flags,
    }


def analysis_field_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ANALYSIS_TOP_LEVEL_FIELDS:
        value = metadata.get(key)
        if value in (None, "", [], {}):
            continue
        if value is False:
            continue
        payload[key] = value
    return payload


def apply_pending_safe_summary(record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    record["analysis_stage"] = metadata.get("analysis_stage") or record.get("analysis_stage") or "captured_pending_ai_pass1"
    if metadata.get("analysis_ready"):
        record["tldr"] = metadata.get("tldr") or ""
        record.pop("preview_text", None)
        return record
    record["preview_text"] = metadata.get("preview_text") or ""
    record.pop("tldr", None)
    for key in ANALYSIS_TOP_LEVEL_FIELDS:
        if key in {"primary_ticker", "mentioned_only_tickers", "context_tickers"}:
            continue
        record.pop(key, None)
    if metadata.get("primary_ticker") and metadata.get("primary_ticker") != "UNKNOWN":
        record["primary_ticker"] = metadata["primary_ticker"]
    else:
        record.pop("primary_ticker", None)
    mentioned = metadata.get("mentioned_only_tickers") or []
    if mentioned:
        record["mentioned_only_tickers"] = mentioned
    else:
        record.pop("mentioned_only_tickers", None)
    record.pop("context_tickers", None)
    return record


def infer_tags(items: list[dict], thread_type: str, tickers: list[str]) -> list[str]:
    return generic_infer_tags(
        items,
        thread_type,
        tickers,
        thread_filter_config(),
        display_text,
        explicit_x_links,
        media_keys,
        lambda item: bool((item.get("note_tweet") or {}).get("text")),
    )


def rough_tldr(items: list[dict]) -> str:
    ordered = sorted(items, key=lambda x: x.get("created_at") or "")
    source_items = [item for item in ordered if item.get("author_id") == SOURCE_USER_ID]
    source = source_items[0] if source_items else (ordered[0] if ordered else {})
    words = display_text(source).strip().replace("\n", " ").split()
    return " ".join(words[:55]) + ("..." if len(words) > 55 else "")


def classify_thread(root: dict | None, items: list[dict]) -> str:
    if root and root.get("author_id") == SOURCE_USER_ID:
        return configured_thread_label("source_started_thread", "SOURCE_THREAD")
    if any(item.get("author_id") == SOURCE_USER_ID for item in items):
        return configured_thread_label("source_reply_context", "SOURCE_REPLY_CONTEXT")
    return configured_thread_label("linked_context", "LINKED_CONTEXT")


def thread_created_at(root: dict | None, items: list[dict]) -> str:
    if root and root.get("created_at"):
        return root["created_at"]
    created = sorted(item.get("created_at") or "" for item in items if item.get("created_at"))
    return created[0] if created else ""


def write_usage_estimate(root: Path, run_id: str, client: XClient) -> dict:
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


def checkpoint(name: str, **fields: object) -> None:
    if REPORTER:
        REPORTER.emit("CHECKPOINT", checkpoint=name, **fields)
    else:
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        print(f"CHECKPOINT {name}{(' ' + suffix) if suffix else ''}", flush=True)


def configure_source(profile: SourceProfile) -> None:
    global SOURCE_PROFILE, SOURCE_USERNAME, SOURCE_USER_ID, SOURCE_DISPLAY_NAME, SOURCE_THREAD_RULES, SOURCE_MEDIA_RULES
    SOURCE_PROFILE = profile
    SOURCE_USERNAME = profile.username
    SOURCE_USER_ID = profile.user_id
    SOURCE_DISPLAY_NAME = profile.display_name
    SOURCE_THREAD_RULES, SOURCE_MEDIA_RULES = load_source_rules(profile)
    if profile.data_root and not os.environ.get("INVESTMENT_TOOL_DATA_DIR"):
        os.environ["INVESTMENT_TOOL_DATA_DIR"] = str(Path(profile.data_root).expanduser().parent)


def entries_from_cached_json(json_dir: Path, threads_dir: Path) -> list[dict]:
    entries: list[dict] = []
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
                "source_posts": sum(1 for tweet in tweets if tweet.get("author_id") == SOURCE_USER_ID),
                "photos": sum(len(media_keys(tweet)) for tweet in tweets),
                **source_entry_fields(data),
            }
        )
    return entries


def apply_cached_relevance_gate(root: Path, json_dir: Path, threads_dir: Path) -> int:
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
        thread_type = data.get("type") or classify_thread(root_tweet, items)
        reason = ignore_reason(root_tweet, items, thread_type, tickers)
        if not reason:
            continue
        move_generated_json_to_ignored(root, json_path, threads_dir, data, reason)
        ignored += 1
    return ignored


def rerender_cached_threads(
    root: Path,
    json_dir: Path,
    threads_dir: Path,
    conversation_id: str | None,
) -> list[dict]:
    entries: list[dict] = []
    for source_json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(source_json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        conv_id = data.get("conversation_id")
        if not conv_id or (conversation_id and conv_id != conversation_id):
            continue
        if data.get("ignored"):
            move_generated_json_to_ignored(root, source_json_path, threads_dir, data, data.get("ignored_reason") or "IGNORED")
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
        relevance_tickers = source_conversation_tickers(root_tweet, items)
        thread_type = classify_thread(root_tweet, items)
        tags = list(dict.fromkeys(infer_tags(items, thread_type, metadata_tickers) + media_placeholder_tags(items, local_media)))
        label = primary_label(metadata_tickers, tags)
        title = title_with_label_prefix(title, label)
        reason = ignore_reason(root_tweet, items, thread_type, relevance_tickers)
        if reason:
            move_generated_json_to_ignored(root, source_json_path, threads_dir, data, reason)
            continue
        tldr = rough_tldr(items)
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
            root,
            SOURCE_USERNAME,
            SOURCE_USER_ID,
        )
        updated = apply_pending_safe_summary({
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
            "non_photo_media": non_photo_media_placeholders(items, local_media),
        }, analysis_metadata)
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
                "source_posts": sum(1 for item in items if item.get("author_id") == SOURCE_USER_ID),
                "photos": sum(len(media_keys(item)) for item in items),
                **source_entry_fields(updated),
            }
        )
    if conversation_id:
        processed = {entry["conversation_id"] for entry in entries}
        entries.extend(entry for entry in entries_from_cached_json(json_dir, threads_dir) if entry["conversation_id"] not in processed)
    return entries or entries_from_cached_json(json_dir, threads_dir)


def repair_cached_media_paths(json_dir: Path, backup_root: Path) -> dict[str, int | str]:
    backup_dir = backup_root / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S_media_path_repair")
    stats = {
        "scanned": 0,
        "changed": 0,
        "unchanged": 0,
        "failed": 0,
        "removed_media_path_refs": 0,
        "media_free_paths_cleared": 0,
        "backup_dir": str(backup_dir),
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


def conversation_ids_from_raw_tweets(tweets: dict[str, dict]) -> set[str]:
    return {
        str(tweet["conversation_id"])
        for tweet in tweets.values()
        if tweet.get("author_id") == SOURCE_USER_ID and tweet.get("conversation_id")
    }


def group_raw_conversations(tweets: dict[str, dict], conversation_ids: set[str]) -> dict[str, list[dict]]:
    by_conversation: dict[str, list[dict]] = defaultdict(list)
    for tweet in tweets.values():
        conv = tweet.get("conversation_id")
        if conv in conversation_ids:
            by_conversation[str(conv)].append(tweet)
    for conversation_id, items in list(by_conversation.items()):
        included_ids = {item.get("id") for item in items}
        for item in list(items):
            if item.get("author_id") != SOURCE_USER_ID and item.get("id") != conversation_id:
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
) -> tuple[dict[str, Any], str, str]:
    root_tweet = tweets.get(conversation_id)
    title, slug = thread_title(root_tweet, items)
    source_items = [item for item in items if item.get("author_id") == SOURCE_USER_ID]
    op_tickers = root_post_tickers(root_tweet)
    metadata_tickers = root_primary_tickers(root_tweet)
    relevance_tickers = source_conversation_tickers(root_tweet, items)
    thread_type = classify_thread(root_tweet, items)
    local_media = thread_local_media(media, items)
    local_paths = thread_local_media_paths(all_media_paths, items)
    tags = list(dict.fromkeys(infer_tags(items, thread_type, metadata_tickers) + media_placeholder_tags(items, local_media)))
    label = primary_label(metadata_tickers, tags)
    title = title_with_label_prefix(title, label)
    reason = ignore_reason(root_tweet, items, thread_type, relevance_tickers)
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
        "preview_text": rough_tldr(items),
        "analysis_stage": "raw_rebuilt_pending_media_description",
        "completeness_status": "rebuilt_from_saved_raw_api",
        "rebuilt_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tweets": items,
        "users": thread_user_map(items, users),
        "media": local_media,
        "media_paths": local_paths,
        "non_photo_media": non_photo_media_placeholders(items, local_media),
        "missing_media": missing_media_keys(items, local_media, local_paths),
        "source": x_source_record(kind="saved_x_raw_api_rebuild", raw_api_used=True, x_api_called=False),
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


def rebuild_from_raw_api(root: Path, staging_dir: Path, replace_active: bool) -> dict[str, Any]:
    raw_root = root / "raw_api"
    media_dir = root / "media"
    tweets, users, media, raw_stats = load_raw_api_archive(raw_root)
    media_paths = existing_local_media_paths(media_dir)
    conversation_ids = conversation_ids_from_raw_tweets(tweets)
    by_conversation = group_raw_conversations(tweets, conversation_ids)
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


def recover_missing_media_metadata(root: Path, client: XClient) -> dict[str, Any]:
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
    placeholder_types = set(SOURCE_MEDIA_RULES.get("placeholder_types") or ["video", "animated_gif"])
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


def main() -> int:
    global REPORTER
    parser = argparse.ArgumentParser(description="Capture configured X source threads into readable local HTML files.")
    parser.add_argument("--source-config", default="config/sources/x_accounts.json")
    parser.add_argument("--source-id", default="")
    parser.add_argument("--timeline-pages", type=int, default=3)
    parser.add_argument("--conversation-pages", type=int, default=0, help="Override configured conversation page depth.")
    parser.add_argument("--max-threads", type=int, default=20)
    parser.add_argument("--conversation-id")
    parser.add_argument("--force", action="store_true", help="Re-fetch and overwrite already-cached threads")
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
    args = parser.parse_args()
    if args.analyze:
        print("capture_threads no longer runs AI. Use the configured AI pass pipeline for thread analysis.", file=sys.stderr)
        return 2

    env_path = Path.cwd() / ".env"
    load_env(env_path)
    configure_source(load_x_source_profile(args.source_config, args.source_id))
    if args.conversation_pages <= 0:
        args.conversation_pages = int(SOURCE_THREAD_RULES.get("conversation_pages") or 5)

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = data_root() / "x_threads"
    raw_dir = root / "raw_api" / run_id
    json_dir = root / "thread_json"
    media_dir = root / "media"
    threads_dir = root / "threads"
    for folder in (raw_dir, json_dir, media_dir, threads_dir, root / "indexes"):
        folder.mkdir(parents=True, exist_ok=True)

    if args.repair_media_paths:
        stats = repair_cached_media_paths(json_dir, root / "cleanup_backups")
        for key, value in stats.items():
            print(f"{key.upper()}={value}")
        return 0 if int(stats["failed"]) == 0 else 1

    if args.rebuild_from_raw_api:
        staging_dir = (
            Path(args.rebuild_staging_dir).expanduser()
            if args.rebuild_staging_dir
            else root / "rebuild_staging" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        REPORTER = start_reporter(
            "x_capture",
            mode="raw_rebuild_replace" if args.replace_generated_json else "raw_rebuild_staging",
            raw_dir=root / "raw_api",
            staging_dir=staging_dir,
            replace_generated_json=args.replace_generated_json,
        )
        manifest = rebuild_from_raw_api(root, staging_dir, args.replace_generated_json)
        REPORTER.done(**manifest)
        for key, value in manifest.items():
            print(f"{key.upper()}={value}")
        return 0 if int(manifest.get("failed_raw_files") or 0) == 0 else 1

    REPORTER = start_reporter(
        "x_capture",
        total=args.max_threads,
        every_items=10,
        every_seconds=30,
        mode=(
            "recover_missing_media"
            if args.recover_missing_media_metadata
            else "reindex"
            if args.reindex_only
            else "rerender"
            if args.rerender_only
            else "capture"
        ),
        timeline_pages=args.timeline_pages,
        conversation_pages=args.conversation_pages,
        max_threads=args.max_threads,
        conversation_id=args.conversation_id or "",
        ai_in_capture="false",
        ai_pipeline="separate_thread_passes",
        x_usage_available="usage_endpoint_when_supported",
        openai_usage_available="not_used_by_capture",
        raw_dir=raw_dir,
    )

    if args.reindex_only:
        ignored = apply_cached_relevance_gate(root, json_dir, threads_dir)
        entries = entries_from_cached_json(json_dir, threads_dir)
        render_all_indexes(root, entries, load_owned_tickers())
        print(f"INDEX={root / 'indexes' / 'index.html'}")
        print("REINDEX_ONLY=true")
        print(f"THREADS={len(entries)}")
        print(f"IGNORED={ignored}")
        print("API_CALLS=0")
        REPORTER.done(mode="reindex", threads=len(entries), ignored=ignored, api_calls=0, index=root / "indexes" / "index.html")
        return 0

    if args.rerender_only:
        ignored = apply_cached_relevance_gate(root, json_dir, threads_dir)
        entries = rerender_cached_threads(root, json_dir, threads_dir, args.conversation_id)
        render_all_indexes(root, entries, load_owned_tickers())
        print(f"INDEX={root / 'indexes' / 'index.html'}")
        print("RERENDER_ONLY=true")
        print(f"THREADS={len(entries)}")
        print(f"IGNORED={ignored}")
        print("API_CALLS=0")
        REPORTER.done(mode="rerender", threads=len(entries), ignored=ignored, api_calls=0, index=root / "indexes" / "index.html")
        return 0

    token = os.environ.get("X_USER_ACCESS_TOKEN", "").strip()
    if not token:
        print("Missing X_USER_ACCESS_TOKEN in .env", file=sys.stderr)
        return 1

    if args.recover_missing_media_metadata:
        client = XClient(token, raw_dir, refresh_callback=lambda: refresh_x_user_token(env_path))
        stats = recover_missing_media_metadata(root, client)
        REPORTER.done(**stats, raw_dir=raw_dir)
        for key, value in stats.items():
            print(f"{key.upper()}={value}")
        return 0

    client = XClient(token, raw_dir, refresh_callback=lambda: refresh_x_user_token(env_path))
    tweets: dict[str, dict] = {}
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}

    cached_tweet_ids = load_cached_threads(json_dir, tweets, users, media)
    cached_conversation_ids = set(cached_tweet_ids.keys())
    if cached_conversation_ids:
        print(f"CACHED={len(cached_conversation_ids)} threads found locally")

    checkpoint("X_TIMELINE_FETCH_START", pages=args.timeline_pages)
    seed_ids = fetch_timeline(client, SOURCE_USER_ID, args.timeline_pages, tweets, users, media)
    checkpoint("X_TIMELINE_FETCH_DONE", seed_posts=len(seed_ids), total_posts=len(tweets), api_calls=client.call_count)
    if args.conversation_id:
        seed_ids.append(args.conversation_id)
        fetch_tweets_by_ids(client, [args.conversation_id], tweets, users, media, "requested_conversation")
        checkpoint("X_REQUESTED_CONVERSATION_FETCH_DONE", conversation_id=args.conversation_id, api_calls=client.call_count)
    checkpoint("X_CONTEXT_WALK_START", seed_posts=len(seed_ids))
    walk_context(client, seed_ids, tweets, users, media)
    checkpoint("X_CONTEXT_WALK_DONE", total_posts=len(tweets), users=len(users), media=len(media), api_calls=client.call_count)

    conversation_ids: list[str] = []
    if args.conversation_id:
        conversation_ids = [args.conversation_id]
    else:
        for tweet in sorted(tweets.values(), key=lambda item: item.get("created_at") or "", reverse=True):
            if tweet.get("author_id") != SOURCE_USER_ID:
                continue
            conv = tweet.get("conversation_id")
            if conv and conv not in conversation_ids:
                conversation_ids.append(conv)
            if len(conversation_ids) >= args.max_threads:
                break
    checkpoint("THREAD_DISCOVERY_DONE", conversations=len(conversation_ids), cached=len(cached_conversation_ids))

    # A cached thread has new replies if the timeline fetch introduced tweet IDs
    # that weren't in the stored JSON. Those threads need a full conversation
    # search so we pick up any replies we haven't seen yet.
    def has_new_tweets(conv_id: str) -> bool:
        known = cached_tweet_ids.get(conv_id, set())
        current = {tid for tid, t in tweets.items() if t.get("conversation_id") == conv_id}
        return bool(current - known)

    search_counts: dict[str, int] = {}
    conversation_search_run = 0
    conversation_search_skipped = 0
    for conversation_id in conversation_ids:
        if not args.force and conversation_id in cached_conversation_ids and not has_new_tweets(conversation_id):
            search_counts[conversation_id] = 0
            conversation_search_skipped += 1
            continue
        conversation_search_run += 1
        checkpoint("X_CONVERSATION_SEARCH_START", conversation_id=conversation_id, pages=args.conversation_pages)
        search_counts[conversation_id] = search_conversation(
            client, conversation_id, tweets, users, media, args.conversation_pages
        )
        conv_ids = [tweet_id for tweet_id, tweet in tweets.items() if tweet.get("conversation_id") == conversation_id]
        walk_context(client, conv_ids, tweets, users, media)
        checkpoint(
            "X_CONVERSATION_SEARCH_DONE",
            conversation_id=conversation_id,
            search_results=search_counts[conversation_id],
            conversation_posts=len(conv_ids),
            api_calls=client.call_count,
        )
    checkpoint("X_CONVERSATION_SEARCH_SUMMARY", searched=conversation_search_run, skipped_cached=conversation_search_skipped)

    by_conversation: dict[str, list[dict]] = defaultdict(list)
    for tweet in tweets.values():
        conv = tweet.get("conversation_id")
        if conv in conversation_ids:
            by_conversation[conv].append(tweet)
    for conversation_id, items in list(by_conversation.items()):
        included_ids = {item.get("id") for item in items}
        for item in list(items):
            if item.get("author_id") != SOURCE_USER_ID and item.get("id") != conversation_id:
                continue
            for qid in quoted_ids(item):
                quoted = tweets.get(qid)
                if quoted and qid not in included_ids:
                    by_conversation[conversation_id].append(quoted)
                    included_ids.add(qid)

    entries: list[dict] = []
    wanted_media_keys = {key for items in by_conversation.values() for item in items for key in media_keys(item)}
    checkpoint("MEDIA_DOWNLOAD_START", photos=len(wanted_media_keys))
    media_paths = download_photos(media, media_dir, wanted_media_keys)
    checkpoint("MEDIA_DOWNLOAD_DONE", downloaded=len(media_paths), requested=len(wanted_media_keys))
    ignored_this_run = 0
    checkpoint("THREAD_RENDER_START", conversations=len(by_conversation), ai_enabled=False)
    for conversation_id, items in by_conversation.items():
        existing_record = find_cached_thread_record(json_dir, conversation_id)
        existing_data = existing_record[1] if existing_record else {}
        local_media = thread_local_media(media, items)
        local_media_paths = thread_local_media_paths(media_paths, items)
        root_tweet = tweets.get(conversation_id)
        created_at = thread_created_at(root_tweet, items)
        title, slug = thread_title(root_tweet, items)
        op_tickers = root_post_tickers(root_tweet)
        metadata_tickers = root_primary_tickers(root_tweet)
        relevance_tickers = source_conversation_tickers(root_tweet, items)
        thread_type = classify_thread(root_tweet, items)
        tags = list(dict.fromkeys(infer_tags(items, thread_type, metadata_tickers) + media_placeholder_tags(items, local_media)))
        label = primary_label(metadata_tickers, tags)
        title = title_with_label_prefix(title, label)
        reason = ignore_reason(root_tweet, items, thread_type, relevance_tickers)
        if reason:
            ignored_this_run += 1
            checkpoint("THREAD_IGNORED", conversation_id=conversation_id, reason=reason)
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
                "non_photo_media": non_photo_media_placeholders(items, local_media),
                "source": x_source_record(kind="live_capture_or_cached_update", raw_api_used=True, x_api_called=True),
                "ignored": True,
                "ignored_reason": reason,
                "ignored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            if existing_record:
                existing_json_path, existing_json_data = existing_record
                existing_json_data.update(ignored_data)
                move_generated_json_to_ignored(root, existing_json_path, threads_dir, existing_json_data, reason)
            else:
                write_ignored_record(root, conversation_id, reason, ignored_data)
                remove_thread_htmls(threads_dir, conversation_id, ignored_data.get("canonical_filename"))
            continue
        tldr = rough_tldr(items)
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
        html_path = threads_dir / filename
        json_path = json_dir / f"{prefix}__{label}__{slug}__{conversation_id}.json"
        is_cached = not args.force and conversation_id in cached_conversation_ids and not has_new_tweets(conversation_id)
        cached_record = existing_record if is_cached else None
        if cached_record:
            cached_json_path, cached_data = cached_record
            cached_filename = cached_data.get("canonical_filename")
            if cached_filename:
                json_path = cached_json_path
                html_path = threads_dir / cached_filename
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
            cleanup_old_thread_versions(json_dir, threads_dir, conversation_id, json_path, html_path)
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
                root,
                SOURCE_USERNAME,
                SOURCE_USER_ID,
            )
        if not is_cached:
            json_path.write_text(
                json.dumps(
                    apply_pending_safe_summary({
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
                        "non_photo_media": non_photo_media_placeholders(items, local_media),
                        "source": x_source_record(kind="live_capture", raw_api_used=True, x_api_called=True),
                        "rate_limits": client.rate_limits,
                    }, analysis_metadata),
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        # For cached threads read captured_at from the existing JSON so
        # relative-time display in the index stays accurate across runs.
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
                "source_posts": sum(1 for item in items if item.get("author_id") == SOURCE_USER_ID),
                "photos": sum(len(media_keys(item)) for item in items),
                **source_entry_fields(existing_data),
            }
        )

    checkpoint(
        "THREAD_RENDER_DONE",
        rendered=len(entries),
        ignored=ignored_this_run,
        ai_enabled=False,
    )

    # Include all cached threads that weren't in this run's conversation_ids
    # so the index always shows the full archive, not just the last N threads.
    processed_ids = {e["conversation_id"] for e in entries}
    entries.extend(entry for entry in entries_from_cached_json(json_dir, threads_dir) if entry["conversation_id"] not in processed_ids)

    render_all_indexes(root, entries, load_owned_tickers())
    checkpoint("INDEX_RENDER_DONE", entries=len(entries), index=root / "indexes" / "index.html")
    usage = write_usage_estimate(root, run_id, client)
    print(f"INDEX={root / 'indexes' / 'index.html'}")
    print(f"THREADS={len(entries)}")
    print(f"RAW_API_DIR={raw_dir}")
    print(f"MEDIA_DIR={media_dir}")
    print(f"API_CALLS={client.call_count}")
    print(f"UNIQUE_POST_READS_ESTIMATE={usage['unique_post_ids_returned']}")
    print(f"ESTIMATED_X_COST_USD={usage['estimated_cost_usd']}")
    print("AI_IN_CAPTURE=false")
    REPORTER.done(
        threads=len(entries),
        ignored=ignored_this_run,
        api_calls=client.call_count,
        unique_post_reads_estimate=usage["unique_post_ids_returned"],
        estimated_x_cost_usd=usage["estimated_cost_usd"],
        ai_in_capture=False,
        index=root / "indexes" / "index.html",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
