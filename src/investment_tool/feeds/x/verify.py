"""Read-only health checks for stored X feed records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from investment_tool.feeds.x.threads import media_keys, thread_media_keys


FINAL_AI_FIELDS = {
    "final_priority",
    "final_signal",
    "final_actionability_score",
    "final_portfolio_state",
}
PENDING_AI_FIELDS = {
    "priority",
    "signal",
    "stance",
    "category",
    "actionability_score",
    "confidence",
    "screenshot_importance",
    "ocr_needed",
    "linked_context_required",
}


def is_present(value: object) -> bool:
    return value not in (None, "", [], {})


def is_pending_record(data: dict[str, Any]) -> bool:
    stage = str(data.get("analysis_stage") or "").lower()
    return "pending" in stage or not data.get("analysis")


def record_issues(path: Path, data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tweets = data.get("tweets") or []
    if not isinstance(tweets, list):
        tweets = []
    expected_media_keys = thread_media_keys(tweets)
    media_paths = data.get("media_paths") or {}
    media = data.get("media") or {}
    if not isinstance(media_paths, dict):
        media_paths = {}
    if not isinstance(media, dict):
        media = {}

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for field in ("conversation_id", "created_at", "type", "feed"):
        if not is_present(data.get(field)):
            violations.append({"file": path.name, "code": "missing_required_field", "field": field})

    feed = data.get("feed") if isinstance(data.get("feed"), dict) else {}
    for field in ("feed_id", "platform", "username", "user_id"):
        if not is_present(feed.get(field)):
            violations.append({"file": path.name, "code": "missing_feed_identity", "field": field})

    extra_media_paths = sorted(set(media_paths) - expected_media_keys)
    if extra_media_paths:
        violations.append({"file": path.name, "code": "global_media_paths", "media_keys": extra_media_paths})
    extra_media_metadata = sorted(set(media) - expected_media_keys)
    if extra_media_metadata:
        violations.append({"file": path.name, "code": "global_media_metadata", "media_keys": extra_media_metadata})
    if not expected_media_keys and media_paths:
        violations.append({"file": path.name, "code": "media_free_thread_has_paths", "media_keys": sorted(media_paths)})

    if any(key for tweet in tweets for key in media_keys(tweet)):
        non_photo_keys = {
            str(item.get("media_key"))
            for item in data.get("non_photo_media") or []
            if isinstance(item, dict) and item.get("media_key")
        }
        missing_paths = sorted(
            key
            for key in expected_media_keys
            if key not in media_paths and key not in non_photo_keys
        )
        if missing_paths:
            warnings.append({"file": path.name, "code": "media_reference_without_path_or_placeholder", "media_keys": missing_paths})

    final_fields = sorted(field for field in FINAL_AI_FIELDS if is_present(data.get(field)))
    if final_fields:
        violations.append({"file": path.name, "code": "final_ai_fields_in_feed_record", "fields": final_fields})

    if is_pending_record(data):
        pending_fields = sorted(field for field in PENDING_AI_FIELDS if is_present(data.get(field)))
        if pending_fields:
            violations.append({"file": path.name, "code": "pending_record_has_ai_fields", "fields": pending_fields})

    return violations, warnings


def verify_x_records(records_dir: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "records_dir": str(records_dir),
        "records": 0,
        "invalid_json": 0,
        "violations": [],
        "warnings": [],
        "violation_count": 0,
        "warning_count": 0,
    }
    if not records_dir.exists():
        return stats
    for path in sorted(records_dir.glob("*.json")):
        stats["records"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            stats["invalid_json"] += 1
            stats["violations"].append({"file": path.name, "code": "invalid_json", "error": str(exc)})
            continue
        if not isinstance(data, dict):
            stats["violations"].append({"file": path.name, "code": "record_not_object"})
            continue
        violations, warnings = record_issues(path, data)
        stats["violations"].extend(violations)
        stats["warnings"].extend(warnings)
    stats["violation_count"] = len(stats["violations"])
    stats["warning_count"] = len(stats["warnings"])
    return stats
