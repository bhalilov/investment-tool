"""Canonical runtime storage paths.

All production code should resolve runtime paths through this module instead of
hardcoding user-specific folders or old storage names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DATA_TOKEN = "<data>"
REPO_TOKEN = "<repo>"


def repo_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return path.parents[3]


def project_home() -> Path:
    configured = os.environ.get("INVESTMENT_TOOL_HOME", "").strip()
    return resolve_path(configured, base=Path.cwd()) if configured else repo_root()


def resolve_path(value: str | Path, base: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return ((base or project_home()) / path).resolve()


def default_data_root() -> Path:
    return project_home() / "data"


def runtime_data_root(value: str | Path | None = None) -> Path:
    # One resolver keeps CLI flags, env vars, and portable tokens behaving the
    # same way across capture, render, tests, and maintenance jobs.
    if value:
        text = str(value)
        if text == DATA_TOKEN or text.startswith(f"{DATA_TOKEN}/"):
            return resolve_portable_path(text, default_data_root()).resolve()
        if text == REPO_TOKEN or text.startswith(f"{REPO_TOKEN}/"):
            return resolve_portable_path(text, default_data_root()).resolve()
        return resolve_path(value)
    configured = os.environ.get("INVESTMENT_TOOL_DATA_DIR", "").strip()
    return runtime_data_root(configured) if configured else default_data_root()


def data_root_for_x_root(value: str | Path) -> Path:
    text = str(value)
    path = resolve_portable_path(text) if text.startswith((DATA_TOKEN, REPO_TOKEN)) else resolve_path(value)
    if path.name == "x" and path.parent.name == "feeds":
        return path.parent.parent
    if path.name == "x_threads":
        return path.parent
    return runtime_data_root()


@dataclass(frozen=True)
class StoragePaths:
    root: Path

    @property
    def feeds(self) -> Path:
        return self.root / "feeds"

    @property
    def x_root(self) -> Path:
        return self.feeds / "x"

    @property
    def x_raw(self) -> Path:
        return self.x_root / "raw"

    def x_raw_run(self, run_id: str) -> Path:
        return self.x_raw / run_id

    @property
    def x_records(self) -> Path:
        return self.x_root / "records"

    @property
    def x_media(self) -> Path:
        return self.x_root / "media"

    @property
    def x_ignored(self) -> Path:
        return self.x_root / "ignored"

    @property
    def x_rebuild(self) -> Path:
        return self.x_root / "rebuild"

    @property
    def x_backups(self) -> Path:
        return self.x_root / "backups"

    @property
    def x_usage(self) -> Path:
        return self.x_root / "usage"

    @property
    def articles_root(self) -> Path:
        return self.feeds / "articles"

    @property
    def articles_archive(self) -> Path:
        return self.articles_root / "archive"

    @property
    def articles_records(self) -> Path:
        return self.articles_root / "records"

    @property
    def articles_manifest(self) -> Path:
        return self.articles_root / "manifest.json"

    @property
    def screenshots_root(self) -> Path:
        return self.feeds / "screenshots"

    @property
    def screenshots_inbox(self) -> Path:
        return self.screenshots_root / "inbox"

    @property
    def screenshots_bundles(self) -> Path:
        return self.screenshots_root / "bundles"

    @property
    def screenshots_media(self) -> Path:
        return self.screenshots_root / "media"

    @property
    def screenshots_records(self) -> Path:
        return self.screenshots_root / "records"

    @property
    def context_root(self) -> Path:
        return self.root / "context"

    @property
    def prices_root(self) -> Path:
        return self.context_root / "prices"

    @property
    def prices_daily(self) -> Path:
        return self.prices_root / "daily"

    @property
    def prices_hourly(self) -> Path:
        return self.prices_root / "hourly"

    @property
    def prices_intraday(self) -> Path:
        return self.prices_root / "intraday"

    @property
    def prices_manifest(self) -> Path:
        return self.prices_root / "manifest.json"

    @property
    def descriptions_root(self) -> Path:
        return self.context_root / "descriptions"

    @property
    def x_descriptions(self) -> Path:
        return self.descriptions_root / "x"

    @property
    def screenshot_descriptions(self) -> Path:
        return self.descriptions_root / "screenshots"

    @property
    def presentation_root(self) -> Path:
        return self.root / "presentation"

    @property
    def x_threads_html(self) -> Path:
        return self.presentation_root / "threads" / "x"

    @property
    def indexes(self) -> Path:
        return self.presentation_root / "indexes"

    @property
    def retrieval_root(self) -> Path:
        return self.root / "retrieval"

    @property
    def legacy_retrieval_root(self) -> Path:
        return self.retrieval_root / "legacy"

    @property
    def legacy_x_root(self) -> Path:
        return self.legacy_retrieval_root / "x"

    @property
    def legacy_x_evidence(self) -> Path:
        return self.legacy_x_root / "evidence"

    @property
    def legacy_x_manifest(self) -> Path:
        return self.legacy_x_root / "manifest.json"

    @property
    def legacy_articles_root(self) -> Path:
        return self.legacy_retrieval_root / "articles"

    @property
    def legacy_articles_evidence(self) -> Path:
        return self.legacy_articles_root / "evidence"

    @property
    def workflow_root(self) -> Path:
        return self.root / "workflow"

    @property
    def workflow_logs(self) -> Path:
        return self.workflow_root / "logs"

    @property
    def workflow_locks(self) -> Path:
        return self.workflow_root / "locks"

    @property
    def storage_rename_manifest(self) -> Path:
        return self.workflow_logs / "storage_rename_manifest.json"

    @property
    def legacy_root(self) -> Path:
        return self.root / "legacy"

    @property
    def legacy_probes(self) -> Path:
        return self.legacy_root / "probes"

    @property
    def legacy_unsorted(self) -> Path:
        return self.legacy_root / "unsorted"

    @property
    def legacy_old_captures(self) -> Path:
        return self.legacy_root / "old-captures"

    def ensure_runtime_dirs(self, include_planned: bool = False) -> None:
        folders = [
            self.x_raw,
            self.x_records,
            self.x_media,
            self.x_ignored,
            self.x_usage,
            self.articles_archive,
            self.articles_records,
            self.screenshots_inbox,
            self.screenshots_bundles,
            self.screenshots_media,
            self.screenshots_records,
            self.prices_daily,
            self.x_descriptions,
            self.screenshot_descriptions,
            self.x_threads_html,
            self.indexes,
            self.workflow_logs,
            self.workflow_locks,
        ]
        if include_planned:
            folders.extend([self.prices_hourly, self.prices_intraday])
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)


def storage_paths(root: str | Path | None = None) -> StoragePaths:
    return StoragePaths(runtime_data_root(root))


def storage_paths_for_x_root(x_root: str | Path | None = None) -> StoragePaths:
    if not x_root:
        return storage_paths()
    return storage_paths(data_root_for_x_root(x_root))


def portable_path(path: str | Path, root: str | Path | None = None) -> str:
    value = Path(path).expanduser()
    data_root = runtime_data_root(root).resolve()
    repo = repo_root().resolve()
    resolved = value.resolve()
    if resolved == data_root:
        return DATA_TOKEN
    if resolved == repo:
        return REPO_TOKEN
    try:
        return f"{DATA_TOKEN}/{resolved.relative_to(data_root)}"
    except ValueError:
        pass
    try:
        return f"{REPO_TOKEN}/{resolved.relative_to(repo)}"
    except ValueError:
        return str(path)


def resolve_portable_path(value: str | Path, root: str | Path | None = None) -> Path:
    text = str(value)
    data_root = runtime_data_root(root)
    if text == DATA_TOKEN:
        return data_root
    if text.startswith(f"{DATA_TOKEN}/"):
        return data_root / text[len(DATA_TOKEN) + 1 :]
    repo = repo_root()
    if text == REPO_TOKEN:
        return repo
    if text.startswith(f"{REPO_TOKEN}/"):
        return repo / text[len(REPO_TOKEN) + 1 :]
    return resolve_path(text)
