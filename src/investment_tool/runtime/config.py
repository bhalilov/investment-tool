"""Feed, rule, model, and prompt configuration helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_X_FEEDS_CONFIG = PROJECT_ROOT / "config" / "feeds" / "x_accounts.json"


@dataclass(frozen=True)
class FeedProfile:
    feed_id: str
    platform: str
    module: str
    username: str
    user_id: str
    display_name: str
    data_root: str
    alternate_usernames: tuple[str, ...]
    thread_rules_path: Path
    media_rules_path: Path
    user_specifics: dict[str, Any]


@dataclass(frozen=True)
class FeedModule:
    module_id: str
    platform: str
    kind: str
    entrypoint: str
    feed_config: str
    supports: tuple[str, ...]


def project_path(path_text: str | Path) -> Path:
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(project_path(path).read_text(encoding="utf-8"))


def read_text(path: str | Path) -> str:
    return project_path(path).read_text(encoding="utf-8")


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(project_path(path).read_bytes()).hexdigest()


def load_x_feed_profile(config_path: str | Path = DEFAULT_X_FEEDS_CONFIG, feed_id: str = "") -> FeedProfile:
    config = read_json(config_path)
    wanted = feed_id or str(config.get("default_feed_id") or "")
    feeds = config.get("feeds") or []
    feed = next((item for item in feeds if item.get("feed_id") == wanted), None)
    if not feed:
        raise ValueError(f"Feed profile not found: {wanted or '<default>'}")
    account = feed.get("account") or {}
    storage = feed.get("storage") or {}
    return FeedProfile(
        feed_id=str(feed.get("feed_id") or wanted),
        platform=str(feed.get("platform") or "x"),
        module=str(feed.get("module") or "x-capture"),
        username=str(account.get("username") or "").lstrip("@"),
        user_id=str(account.get("user_id") or ""),
        display_name=str(account.get("display_name") or account.get("username") or ""),
        data_root=str(storage.get("data_root") or ""),
        alternate_usernames=tuple(str(item).lstrip("@") for item in account.get("alternate_usernames") or []),
        thread_rules_path=project_path(feed.get("thread_rules") or "config/rules/thread_reconstruction.default.json"),
        media_rules_path=project_path(feed.get("media_rules") or "config/rules/media.default.json"),
        user_specifics=dict(feed.get("user_specifics") or {}),
    )


def load_feed_rules(profile: FeedProfile) -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json(profile.thread_rules_path), read_json(profile.media_rules_path)


def load_feed_modules(path: str | Path = "config/feed_modules.json") -> dict[str, FeedModule]:
    config = read_json(path)
    modules: dict[str, FeedModule] = {}
    for item in config.get("modules") or []:
        module = FeedModule(
            module_id=str(item.get("module_id") or ""),
            platform=str(item.get("platform") or ""),
            kind=str(item.get("kind") or ""),
            entrypoint=str(item.get("entrypoint") or ""),
            feed_config=str(item.get("feed_config") or ""),
            supports=tuple(str(value) for value in item.get("supports") or []),
        )
        if module.module_id:
            modules[module.module_id] = module
    return modules


def load_model_registry(path: str | Path = "config/ai/models.json") -> dict[str, Any]:
    return read_json(path)


def load_pipeline_registry(path: str | Path = "config/ai/pipelines.json") -> dict[str, Any]:
    return read_json(path)


def load_prompt(path: str | Path) -> dict[str, str]:
    resolved = project_path(path)
    return {"path": str(resolved), "sha256": file_sha256(resolved), "text": resolved.read_text(encoding="utf-8")}


def feed_profile_for_prompt(profile: FeedProfile) -> dict[str, Any]:
    return {
        "feed_id": profile.feed_id,
        "platform": profile.platform,
        "username": profile.username,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "alternate_usernames": list(profile.alternate_usernames),
        "user_specifics": profile.user_specifics,
    }


def feed_identity(profile: FeedProfile) -> dict[str, Any]:
    return {
        "feed_id": profile.feed_id,
        "platform": profile.platform,
        "module": profile.module,
        "username": profile.username,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "alternate_usernames": list(profile.alternate_usernames),
    }


def feed_label(profile: FeedProfile) -> str:
    username = f"@{profile.username}" if profile.username else profile.user_id or profile.feed_id
    if profile.display_name and profile.display_name != profile.username:
        return f"{profile.display_name} ({username})"
    return username
