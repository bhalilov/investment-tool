"""Configured context for X capture stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_tool.runtime.config import (
    FeedProfile,
    feed_identity,
    feed_label,
    load_feed_rules,
    load_x_feed_profile,
)
from investment_tool.rules.filters import ThreadFilterConfig


@dataclass(frozen=True)
class XCaptureContext:
    profile: FeedProfile
    thread_rules: dict[str, Any]
    media_rules: dict[str, Any]

    @property
    def username(self) -> str:
        return self.profile.username

    @property
    def user_id(self) -> str:
        return self.profile.user_id

    @property
    def display_name(self) -> str:
        return self.profile.display_name

    @property
    def platform(self) -> str:
        return self.profile.platform

    @property
    def feed_id(self) -> str:
        return self.profile.feed_id

    def configured_thread_label(self, name: str, fallback: str) -> str:
        labels = self.thread_rules.get("thread_type_labels") or {}
        return str(labels.get(name) or fallback)

    def feed_record(self, **capture_fields: Any) -> dict[str, Any]:
        return {
            **feed_identity(self.profile),
            **{key: value for key, value in capture_fields.items() if value is not None},
        }

    def feed_entry_fields(self, data: dict[str, Any] | None = None) -> dict[str, str]:
        feed = (data or {}).get("feed") or {}
        username = str(feed.get("username") or self.username).lstrip("@")
        display_name = str(feed.get("display_name") or self.display_name or username)
        if username:
            display = f"{display_name} (@{username})" if display_name and display_name != username else f"@{username}"
        else:
            display = feed_label(self.profile)
        return {
            "feed_display": display,
            "feed_label": display,
            "feed_platform": str(feed.get("platform") or self.platform),
            "feed_id": str(feed.get("feed_id") or self.feed_id),
        }

    def thread_filter_config(self) -> ThreadFilterConfig:
        return ThreadFilterConfig(
            feed_user_id=self.user_id,
            feed_started_label=self.configured_thread_label("feed_started_thread", "FEED_THREAD"),
            feed_reply_label=self.configured_thread_label("feed_reply_context", "FEED_REPLY_CONTEXT"),
            linked_context_domains=tuple(
                str(item).lower() for item in self.profile.user_specifics.get("linked_context_domains") or []
            ),
            self_promo_patterns=tuple(str(item) for item in self.thread_rules.get("self_promo_patterns") or []),
        )


def load_x_capture_context(
    feed_config: str | Path = "config/feeds/x_accounts.json",
    feed_id: str = "",
) -> XCaptureContext:
    profile = load_x_feed_profile(feed_config, feed_id)
    thread_rules, media_rules = load_feed_rules(profile)
    return XCaptureContext(profile=profile, thread_rules=thread_rules, media_rules=media_rules)
