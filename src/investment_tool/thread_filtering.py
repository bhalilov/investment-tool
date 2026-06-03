"""Source-neutral thread relevance and labeling helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


FINANCE_RE = re.compile(
    r"\b("
    r"stock|stocks|shares|equity|market|markets|nasdaq|s&p|sp500|qqq|spy|portfolio|position|positions|"
    r"buy|bought|sell|sold|trim|trimmed|exit|exited|add|added|short|shorted|cover|covered|"
    r"trade|trading|valuation|multiple|eps|revenue|earnings|margin|guidance|forecast|thesis|"
    r"upside|downside|risk/reward|ipo|options|calls|puts|corridor|price target"
    r")\b",
    re.I,
)
NO_TICKER_FINANCE_RE = re.compile(
    r"\b("
    r"stock|stocks|shares|equity|market|markets|nasdaq|s&p|sp500|qqq|spy|portfolio|"
    r"buy|bought|sell|sold|trim|trimmed|short|shorted|trade|trading|valuation|multiple|eps|"
    r"revenue|earnings|margin|guidance|forecast|thesis|upside|downside|risk/reward|ipo|options|"
    r"calls|puts|corridor|price target"
    r")\b",
    re.I,
)
DEFAULT_SELF_PROMO_PATTERNS = ["subscription", "subscriber", "subscribe", "mustsubscribeto"]


@dataclass(frozen=True)
class ThreadFilterConfig:
    source_user_id: str = ""
    source_started_label: str = "SOURCE_THREAD"
    source_reply_label: str = "SOURCE_REPLY_CONTEXT"
    linked_context_domains: tuple[str, ...] = ()
    self_promo_patterns: tuple[str, ...] = tuple(DEFAULT_SELF_PROMO_PATTERNS)


def self_promo_re(patterns: Iterable[str] = DEFAULT_SELF_PROMO_PATTERNS) -> re.Pattern[str]:
    escaped = [re.escape(str(item)) for item in patterns if str(item)]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.I) if escaped else re.compile(r"$^")


def has_linked_research_domain(text: str, domains: Iterable[str]) -> bool:
    lowered = (text or "").lower()
    return any(str(domain).lower() in lowered for domain in domains if str(domain).strip())


def primary_label(tickers: list[str], tags: list[str]) -> str:
    if tickers:
        return "-".join(tickers[:3])
    for label in ("PERSONAL_FINANCE", "MARKET", "SPACEX", "RANT", "BRAG", "NOISE"):
        if label in tags:
            return label
    return "UNKNOWN"


def normalize_thread_label(value: str | None, tags: list[str]) -> str:
    text = (value or "").strip().lower()
    tag_text = " ".join(tags).lower()
    combined = f"{text} {tag_text}"
    if any(term in combined for term in ("personal", "cash reserve", "burn rate", "discipline", "risk management")):
        return "PERSONAL_FINANCE"
    if any(term in combined for term in ("portfolio", "allocation", "position sizing")):
        return "PORTFOLIO"
    if "spacex" in combined or "starlink" in combined:
        return "SPACEX"
    if any(term in combined for term in ("macro", "market", "s&p", "sp500", "qqq", "spy")):
        return "MARKET"
    if "rant" in combined:
        return "RANT"
    if "brag" in combined:
        return "BRAG"
    return "UNKNOWN"


def source_items(items: list[dict[str, Any]], source_user_id: str) -> list[dict[str, Any]]:
    return [item for item in items if item.get("author_id") == source_user_id]


def relevance_text(
    root: dict[str, Any] | None,
    items: list[dict[str, Any]],
    source_user_id: str,
    text_of: Callable[[dict[str, Any]], str],
) -> str:
    selected = source_items(items, source_user_id)
    parts = [text_of(root or {})] + [text_of(item) for item in selected]
    return "\n".join(part for part in parts if part)


def investment_relevance_score(
    root: dict[str, Any] | None,
    items: list[dict[str, Any]],
    tickers: list[str],
    config: ThreadFilterConfig,
    text_of: Callable[[dict[str, Any]], str],
    linked_post_ids_of: Callable[[dict[str, Any]], list[str]],
    media_keys_of: Callable[[dict[str, Any]], list[str]],
) -> int:
    text = relevance_text(root, items, config.source_user_id, text_of)
    source_only = source_items(items, config.source_user_id)
    score = 0
    score += 4 * len(tickers)
    score += 3 if FINANCE_RE.search(text) else 0
    score += 3 if has_linked_research_domain(text, config.linked_context_domains) else 0
    score += 2 if any(linked_post_ids_of(item) for item in source_only) else 0
    score += 1 if any(media_keys_of(item) for item in source_only) else 0
    return score


def ignore_reason(
    root: dict[str, Any] | None,
    items: list[dict[str, Any]],
    thread_type: str,
    tickers: list[str],
    config: ThreadFilterConfig,
    text_of: Callable[[dict[str, Any]], str],
    is_retweet: Callable[[dict[str, Any] | None], bool],
    linked_post_ids_of: Callable[[dict[str, Any]], list[str]],
    media_keys_of: Callable[[dict[str, Any]], list[str]],
) -> str | None:
    selected = source_items(items, config.source_user_id)
    if not selected:
        return None
    text = relevance_text(root, items, config.source_user_id, text_of)
    score = investment_relevance_score(root, items, tickers, config, text_of, linked_post_ids_of, media_keys_of)
    if root and root.get("author_id") == config.source_user_id and is_retweet(root) and score == 0:
        return "OFF_TOPIC_RETWEET"
    if (
        root
        and root.get("author_id") == config.source_user_id
        and is_retweet(root)
        and not tickers
        and self_promo_re(config.self_promo_patterns).search(text)
    ):
        return "SELF_PROMO_RETWEET"
    if thread_type == config.source_reply_label and not tickers:
        has_linked_research = has_linked_research_domain(text, config.linked_context_domains)
        has_source_link = any(linked_post_ids_of(item) for item in selected)
        has_source_media = any(media_keys_of(item) for item in selected)
        if not has_linked_research and not has_source_link and not has_source_media and not NO_TICKER_FINANCE_RE.search(text):
            return "OFF_TOPIC_REPLY_CONTEXT"
    if thread_type == config.source_reply_label and score == 0:
        return "OFF_TOPIC_REPLY_CONTEXT"
    return None


def infer_tags(
    items: list[dict[str, Any]],
    thread_type: str,
    tickers: list[str],
    config: ThreadFilterConfig,
    text_of: Callable[[dict[str, Any]], str],
    linked_post_ids_of: Callable[[dict[str, Any]], list[str]],
    media_keys_of: Callable[[dict[str, Any]], list[str]],
    has_note_text: Callable[[dict[str, Any]], bool],
) -> list[str]:
    selected = source_items(items, config.source_user_id) or items
    text = "\n".join(text_of(item) for item in selected).lower()
    tags = [thread_type]
    if any(media_keys_of(item) for item in items):
        tags.append("SCREENSHOT")
    if any(has_note_text(item) for item in items):
        tags.append("NOTE_TWEET")
    if any(linked_post_ids_of(item) for item in items):
        tags.append("X_LINKED_CONTEXT")
    if has_linked_research_domain(text, config.linked_context_domains):
        tags.append("GHOST_LINKED")
    if any(term in text for term in ("burn rate", "life planning", "cash requirement", "withdraw", "lifestyle spending")):
        tags.append("PERSONAL_FINANCE")
    if re.search(r"\b(bought|sold|trimmed|exited|added|shorted|covered|closed|reloaded)\b", text):
        tags.append("LIVE_TRADE")
    if re.search(r"\b(buy|sell|avoid|wait|do not chase|risk/reward|too late)\b", text):
        tags.append("ADVICE_WARNING")
    if any(word in text for word in ("valuation", "thesis", "earnings", "multiple", "corridor", "macro", "forecast")):
        tags.append("THESIS_UPDATE")
    if "spacex" in text or "starlink" in text:
        tags.append("SPACEX")
    if not tickers and any(word in text for word in ("s&p", "sp500", "market", "qqq", "spy", "macro")):
        tags.append("MARKET")
    if any(phrase in text for phrase in ("we nailed", "called it", "we called", "nailed it")):
        tags.append("BRAG")
    if any(word in text for word in ("politics", "rant", "nonsense")):
        tags.append("RANT")
    return list(dict.fromkeys(tags))
