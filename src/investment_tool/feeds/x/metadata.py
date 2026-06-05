"""Non-AI metadata helpers for X capture records."""

from __future__ import annotations

import html
import re
from typing import Any

from investment_tool.rules.filters import (
    ignore_reason as generic_ignore_reason,
    infer_tags as generic_infer_tags,
    investment_relevance_score as generic_investment_relevance_score,
    relevance_text as generic_relevance_text,
)
from investment_tool.rules.tickers import (
    TICKER_ALIASES,
    extract_tickers,
    normalize_ticker as normalize_thread_ticker,
)
from investment_tool.feeds.x.context import XCaptureContext
from investment_tool.feeds.x.threads import display_text, explicit_x_links, media_keys


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


def safe_slug(value: str, fallback: str = "thread") -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:90] or fallback


def compact_text(value: str, limit: int = 1800) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] + ("..." if len(value) > limit else "")


def non_photo_media_placeholders(
    items: list[dict[str, Any]],
    media: dict[str, dict],
    context: XCaptureContext,
) -> list[dict[str, Any]]:
    from investment_tool.feeds.x.threads import non_photo_media_placeholders as model_non_photo_media_placeholders

    return model_non_photo_media_placeholders(items, media, context.media_rules)


def media_placeholder_tags(
    items: list[dict[str, Any]],
    media: dict[str, dict],
    context: XCaptureContext,
) -> list[str]:
    from investment_tool.feeds.x.threads import media_placeholder_tags as model_media_placeholder_tags

    return model_media_placeholder_tags(items, media, context.media_rules)


def root_post_tickers(root: dict | None) -> list[str]:
    return extract_tickers(display_text(root or {}))


def root_primary_tickers(root: dict | None) -> list[str]:
    tickers = root_post_tickers(root)
    return tickers if len(tickers) == 1 else []


def feed_conversation_tickers(root: dict | None, items: list[dict], context: XCaptureContext) -> list[str]:
    feed_items = [item for item in items if item.get("author_id") == context.user_id]
    ticker_text = " ".join([display_text(root or {})] + [display_text(item) for item in feed_items])
    return extract_tickers(ticker_text)


def thread_title(root: dict | None, items: list[dict]) -> tuple[str, str]:
    item = root or (items[0] if items else {})
    text = display_text(item)
    tickers = root_primary_tickers(item)
    topic = topic_phrase(text)
    prefix = "/".join(tickers[:3]) if tickers else "X"
    title = f"{prefix} - {topic}"
    return title, safe_slug(topic)


def topic_phrase(text: str) -> str:
    cleaned = html.unescape(re.sub(r"https?://\S+", "", text)).strip()
    first_para = cleaned.split("\n\n", 1)[0].strip()
    if ":" in first_para:
        before, after = first_para.split(":", 1)
        company = next(
            (name.title() for name in TICKER_ALIASES if name.lower() == name and re.search(rf"\b{name}\b", before, re.I)),
            "",
        )
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


def relevance_text(root: dict | None, items: list[dict], context: XCaptureContext) -> str:
    return generic_relevance_text(root, items, context.user_id, display_text)


def investment_relevance_score(root: dict | None, items: list[dict], tickers: list[str], context: XCaptureContext) -> int:
    return generic_investment_relevance_score(
        root,
        items,
        tickers,
        context.thread_filter_config(),
        display_text,
        explicit_x_links,
        media_keys,
    )


def ignore_reason(
    root: dict | None,
    items: list[dict],
    thread_type: str,
    tickers: list[str],
    context: XCaptureContext,
) -> str | None:
    return generic_ignore_reason(
        root,
        items,
        thread_type,
        tickers,
        context.thread_filter_config(),
        display_text,
        is_retweet,
        explicit_x_links,
        media_keys,
    )


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
    """Return display/index metadata without running AI."""
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


def infer_tags(items: list[dict], thread_type: str, tickers: list[str], context: XCaptureContext) -> list[str]:
    return generic_infer_tags(
        items,
        thread_type,
        tickers,
        context.thread_filter_config(),
        display_text,
        explicit_x_links,
        media_keys,
        lambda item: bool((item.get("note_tweet") or {}).get("text")),
    )


def rough_tldr(items: list[dict], feed_user_id: str) -> str:
    ordered = sorted(items, key=lambda x: x.get("created_at") or "")
    feed_items = [item for item in ordered if item.get("author_id") == feed_user_id]
    feed_post = feed_items[0] if feed_items else (ordered[0] if ordered else {})
    words = display_text(feed_post).strip().replace("\n", " ").split()
    return " ".join(words[:55]) + ("..." if len(words) > 55 else "")


def classify_thread(root: dict | None, items: list[dict], context: XCaptureContext) -> str:
    if root and root.get("author_id") == context.user_id:
        return context.configured_thread_label("feed_started_thread", "FEED_THREAD")
    if any(item.get("author_id") == context.user_id for item in items):
        return context.configured_thread_label("feed_reply_context", "FEED_REPLY_CONTEXT")
    return context.configured_thread_label("linked_context", "LINKED_CONTEXT")


def thread_created_at(root: dict | None, items: list[dict]) -> str:
    if root and root.get("created_at"):
        return root["created_at"]
    created = sorted(item.get("created_at") or "" for item in items if item.get("created_at"))
    return created[0] if created else ""
