"""X thread model helpers: text, media ownership, references, and local thread utilities."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


X_STATUS_RE = re.compile(r"https?://(?:mobile\.)?(?:x|twitter)\.com/[^/\s]+/status/(\d+)")


def display_text(tweet: dict[str, Any]) -> str:
    note_text = ((tweet.get("note_tweet") or {}).get("text") or "").strip()
    if note_text:
        return note_text
    return tweet.get("text") or ""


def media_keys(tweet: dict[str, Any]) -> list[str]:
    return (tweet.get("attachments") or {}).get("media_keys") or []


def thread_media_keys(items: list[dict[str, Any]]) -> set[str]:
    return {str(key) for item in items for key in media_keys(item)}


def thread_local_media(media: dict[str, dict], items: list[dict[str, Any]]) -> dict[str, dict]:
    keys = thread_media_keys(items)
    return {key: value for key, value in media.items() if key in keys}


def thread_local_media_paths(media_paths: dict[str, str], items: list[dict[str, Any]]) -> dict[str, str]:
    keys = thread_media_keys(items)
    return {key: value for key, value in media_paths.items() if key in keys}


def non_photo_media_placeholders(
    items: list[dict[str, Any]],
    media: dict[str, dict],
    media_rules: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    media_rules = media_rules or {}
    placeholder_types = set(media_rules.get("placeholder_types") or ["video", "animated_gif"])
    placeholders: list[dict[str, Any]] = []
    for key in sorted(thread_media_keys(items)):
        item = media.get(key) or {}
        media_type = item.get("type")
        if media_type not in placeholder_types:
            continue
        placeholders.append(
            {
                "media_key": key,
                "type": media_type,
                "processing": "ignored_non_photo_media",
                "note": "Video/animated GIF media is recorded as present but is not downloaded or sent to AI media analysis.",
            }
        )
    return placeholders


def media_placeholder_tags(
    items: list[dict[str, Any]],
    media: dict[str, dict],
    media_rules: dict[str, Any] | None = None,
) -> list[str]:
    media_rules = media_rules or {}
    media_types = {item.get("type") for key, item in media.items() if key in thread_media_keys(items)}
    placeholder_tags = media_rules.get("placeholder_tags") or {}
    tags: list[str] = []
    for media_type, tag in placeholder_tags.items():
        if media_type in media_types and tag:
            tags.append(str(tag))
    return tags


def referenced_ids(tweet: dict[str, Any]) -> list[str]:
    return [ref["id"] for ref in tweet.get("referenced_tweets") or [] if ref.get("id")]


def quoted_ids(tweet: dict[str, Any]) -> list[str]:
    return [ref["id"] for ref in tweet.get("referenced_tweets") or [] if ref.get("type") == "quoted" and ref.get("id")]


def parent_id(tweet: dict[str, Any]) -> str | None:
    return next((ref.get("id") for ref in tweet.get("referenced_tweets") or [] if ref.get("type") == "replied_to"), None)


def explicit_x_links(tweet: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    blobs = [tweet.get("entities") or {}, (tweet.get("note_tweet") or {}).get("entities") or {}]
    for blob in blobs:
        for url_obj in blob.get("urls") or []:
            for key in ("expanded_url", "url"):
                value = url_obj.get(key) or ""
                match = X_STATUS_RE.search(value)
                if match:
                    ids.append(match.group(1))
    for match in X_STATUS_RE.finditer(display_text(tweet)):
        ids.append(match.group(1))
    return list(dict.fromkeys(ids))


def existing_local_media_paths(media_dir: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    if not media_dir.exists():
        return paths
    for path in sorted(media_dir.iterdir()):
        if path.is_file():
            paths[path.stem] = str(path)
    return paths


def thread_user_map(items: list[dict[str, Any]], users: dict[str, dict]) -> dict[str, dict]:
    wanted: set[str] = set()
    for item in items:
        for key in ("author_id", "in_reply_to_user_id"):
            if item.get(key):
                wanted.add(str(item[key]))
        for mention in (item.get("entities") or {}).get("mentions") or []:
            if mention.get("id"):
                wanted.add(str(mention["id"]))
    return {user_id: users[user_id] for user_id in sorted(wanted) if user_id in users}


def missing_media_keys(items: list[dict[str, Any]], media: dict[str, dict], media_paths: dict[str, str]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for key in sorted({key for item in items for key in media_keys(item)}):
        if key in media_paths:
            continue
        item = media.get(key) or {}
        missing.append(
            {
                "media_key": key,
                "type": item.get("type") or "unknown",
                "has_metadata": bool(item),
                "reason": "not_downloaded_or_unavailable",
            }
        )
    return missing
