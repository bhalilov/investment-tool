"""Configured context for X capture stages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_tool.source_config import (
    SourceProfile,
    load_source_rules,
    load_x_source_profile,
    source_identity,
    source_label,
)
from investment_tool.thread_filtering import ThreadFilterConfig


@dataclass(frozen=True)
class XCaptureContext:
    profile: SourceProfile
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
    def source_id(self) -> str:
        return self.profile.source_id

    def configured_thread_label(self, name: str, fallback: str) -> str:
        labels = self.thread_rules.get("thread_type_labels") or {}
        return str(labels.get(name) or fallback)

    def source_record(self, **capture_fields: Any) -> dict[str, Any]:
        return {
            **source_identity(self.profile),
            **{key: value for key, value in capture_fields.items() if value is not None},
        }

    def source_entry_fields(self, data: dict[str, Any] | None = None) -> dict[str, str]:
        source = (data or {}).get("source") or {}
        username = str(source.get("username") or self.username).lstrip("@")
        display_name = str(source.get("display_name") or self.display_name or username)
        if username:
            display = f"{display_name} (@{username})" if display_name and display_name != username else f"@{username}"
        else:
            display = source_label(self.profile)
        return {
            "source_display": display,
            "source_label": display,
            "source_platform": str(source.get("platform") or self.platform),
            "source_id": str(source.get("source_id") or self.source_id),
        }

    def thread_filter_config(self) -> ThreadFilterConfig:
        return ThreadFilterConfig(
            source_user_id=self.user_id,
            source_started_label=self.configured_thread_label("source_started_thread", "SOURCE_THREAD"),
            source_reply_label=self.configured_thread_label("source_reply_context", "SOURCE_REPLY_CONTEXT"),
            linked_context_domains=tuple(
                str(item).lower() for item in self.profile.user_specifics.get("linked_context_domains") or []
            ),
            self_promo_patterns=tuple(str(item) for item in self.thread_rules.get("self_promo_patterns") or []),
        )


def load_x_capture_context(
    source_config: str | Path = "config/sources/x_accounts.json",
    source_id: str = "",
) -> XCaptureContext:
    profile = load_x_source_profile(source_config, source_id)
    thread_rules, media_rules = load_source_rules(profile)
    return XCaptureContext(profile=profile, thread_rules=thread_rules, media_rules=media_rules)
