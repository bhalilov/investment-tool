"""Source, rule, model, and prompt configuration helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_X_SOURCES_CONFIG = PROJECT_ROOT / "config" / "sources" / "x_accounts.json"


@dataclass(frozen=True)
class SourceProfile:
    source_id: str
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
class SourceModule:
    module_id: str
    platform: str
    kind: str
    entrypoint: str
    source_config: str
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


def load_x_source_profile(config_path: str | Path = DEFAULT_X_SOURCES_CONFIG, source_id: str = "") -> SourceProfile:
    config = read_json(config_path)
    wanted = source_id or str(config.get("default_source_id") or "")
    sources = config.get("sources") or []
    source = next((item for item in sources if item.get("source_id") == wanted), None)
    if not source:
        raise ValueError(f"Source profile not found: {wanted or '<default>'}")
    account = source.get("account") or {}
    storage = source.get("storage") or {}
    return SourceProfile(
        source_id=str(source.get("source_id") or wanted),
        platform=str(source.get("platform") or "x"),
        module=str(source.get("module") or "x_capture"),
        username=str(account.get("username") or "").lstrip("@"),
        user_id=str(account.get("user_id") or ""),
        display_name=str(account.get("display_name") or account.get("username") or ""),
        data_root=str(storage.get("data_root") or ""),
        alternate_usernames=tuple(str(item).lstrip("@") for item in account.get("alternate_usernames") or []),
        thread_rules_path=project_path(source.get("thread_rules") or "config/rules/thread_reconstruction.default.json"),
        media_rules_path=project_path(source.get("media_rules") or "config/rules/media.default.json"),
        user_specifics=dict(source.get("user_specifics") or {}),
    )


def load_source_rules(profile: SourceProfile) -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json(profile.thread_rules_path), read_json(profile.media_rules_path)


def load_source_modules(path: str | Path = "config/source_modules.json") -> dict[str, SourceModule]:
    config = read_json(path)
    modules: dict[str, SourceModule] = {}
    for item in config.get("modules") or []:
        module = SourceModule(
            module_id=str(item.get("module_id") or ""),
            platform=str(item.get("platform") or ""),
            kind=str(item.get("kind") or ""),
            entrypoint=str(item.get("entrypoint") or ""),
            source_config=str(item.get("source_config") or ""),
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


def source_profile_for_prompt(profile: SourceProfile) -> dict[str, Any]:
    return {
        "source_id": profile.source_id,
        "platform": profile.platform,
        "username": profile.username,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "alternate_usernames": list(profile.alternate_usernames),
        "user_specifics": profile.user_specifics,
    }


def source_identity(profile: SourceProfile) -> dict[str, Any]:
    return {
        "source_id": profile.source_id,
        "platform": profile.platform,
        "module": profile.module,
        "username": profile.username,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "alternate_usernames": list(profile.alternate_usernames),
    }


def source_label(profile: SourceProfile) -> str:
    username = f"@{profile.username}" if profile.username else profile.user_id or profile.source_id
    if profile.display_name and profile.display_name != profile.username:
        return f"{profile.display_name} ({username})"
    return username
