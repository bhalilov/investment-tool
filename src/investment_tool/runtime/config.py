"""Feed, rule, model, and prompt configuration helpers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FEED_MODULES_CONFIG = "config/feed_modules.json"
DEFAULT_X_MODULE_ID = "x-capture"
DEFAULT_ARTICLES_MODULE_ID = "articles"
DEFAULT_AI_PROVIDER = "openai"
DEFAULT_AI_API_BASE = "https://api.openai.com/v1"
DEFAULT_AI_API_KEY_ENV = "OPENAI_API_KEY"


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
    workflow_stages: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class WorkflowStage:
    stage: str
    module_id: str
    platform: str
    kind: str
    entrypoint: str
    feed_config: str
    runner: str
    action: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class AIModelConfig:
    pipeline_id: str
    model_profile: str
    model: str
    provider: str
    api_base: str
    api_key_env: str


def project_path(path_text: str | Path) -> Path:
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(project_path(path).read_text(encoding="utf-8"))


def read_text(path: str | Path) -> str:
    return project_path(path).read_text(encoding="utf-8")


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(project_path(path).read_bytes()).hexdigest()


def load_x_feed_profile(config_path: str | Path | None = None, feed_id: str = "") -> FeedProfile:
    config_path = config_path or default_feed_config(DEFAULT_X_MODULE_ID)
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


def load_feed_modules(path: str | Path = DEFAULT_FEED_MODULES_CONFIG) -> dict[str, FeedModule]:
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
            workflow_stages=tuple(dict(value) for value in item.get("workflow_stages") or []),
        )
        if module.module_id:
            modules[module.module_id] = module
    return modules


def default_feed_config(module_id: str = DEFAULT_X_MODULE_ID) -> str:
    module = load_feed_modules().get(module_id)
    if not module or not module.feed_config:
        raise ValueError(f"Feed module has no configured feed_config: {module_id}")
    return module.feed_config


def load_workflow_stages(path: str | Path = DEFAULT_FEED_MODULES_CONFIG) -> dict[str, WorkflowStage]:
    stages: dict[str, WorkflowStage] = {}
    for module in load_feed_modules(path).values():
        for raw_stage in module.workflow_stages:
            stage = str(raw_stage.get("stage") or "")
            if not stage:
                continue
            stages[stage] = WorkflowStage(
                stage=stage,
                module_id=module.module_id,
                platform=module.platform,
                kind=module.kind,
                entrypoint=module.entrypoint,
                feed_config=module.feed_config,
                runner=str(raw_stage.get("runner") or ""),
                action=str(raw_stage.get("action") or ""),
                argv=tuple(str(value) for value in raw_stage.get("argv") or []),
            )
    return stages


def load_model_registry(path: str | Path = "config/ai/models.json") -> dict[str, Any]:
    return read_json(path)


def load_pipeline_registry(path: str | Path = "config/ai/pipelines.json") -> dict[str, Any]:
    return read_json(path)


def load_pipeline_config(pipeline_id: str, path: str | Path = "config/ai/pipelines.json") -> dict[str, Any]:
    registry = load_pipeline_registry(path)
    for pipeline in registry.get("pipelines") or []:
        if pipeline.get("pipeline_id") == pipeline_id:
            return dict(pipeline)
    raise ValueError(f"Pipeline config not found: {pipeline_id}")


def model_profile_config(profile_id: str, path: str | Path = "config/ai/models.json") -> dict[str, Any]:
    registry = load_model_registry(path)
    profile = (registry.get("model_profiles") or {}).get(profile_id)
    if not profile or not profile.get("model"):
        raise ValueError(f"Model profile not found or missing model: {profile_id}")
    return dict(profile)


def model_for_profile(profile_id: str, path: str | Path = "config/ai/models.json") -> str:
    return str(model_profile_config(profile_id, path)["model"])


def resolve_ai_model_config(
    pipeline_id: str,
    explicit_model: str = "",
    *,
    model_registry_path: str | Path = "config/ai/models.json",
    pipeline_registry_path: str | Path = "config/ai/pipelines.json",
) -> AIModelConfig:
    registry = load_model_registry(model_registry_path)
    pipeline = load_pipeline_config(pipeline_id, pipeline_registry_path)
    profile_id = str(pipeline.get("model_profile") or "")
    if not profile_id:
        raise ValueError(f"Pipeline has no model_profile: {pipeline_id}")
    profile = model_profile_config(profile_id, model_registry_path)
    return AIModelConfig(
        pipeline_id=pipeline_id,
        model_profile=profile_id,
        model=explicit_model or str(profile["model"]),
        provider=str(profile.get("provider") or registry.get("provider") or DEFAULT_AI_PROVIDER),
        api_base=str(profile.get("api_base") or registry.get("api_base") or DEFAULT_AI_API_BASE),
        api_key_env=str(profile.get("api_key_env") or registry.get("api_key_env") or DEFAULT_AI_API_KEY_ENV),
    )


def resolve_ai_model(pipeline_id: str, explicit_model: str = "") -> str:
    return resolve_ai_model_config(pipeline_id, explicit_model).model


def ai_api_key(model_config: AIModelConfig) -> str:
    return os.environ.get(model_config.api_key_env, "").strip()


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
