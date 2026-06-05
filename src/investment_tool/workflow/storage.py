"""Runtime storage maintenance commands."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from investment_tool.runtime.paths import DATA_TOKEN, REPO_TOKEN, StoragePaths, portable_path, repo_root, resolve_portable_path, storage_paths


IGNORABLE_LEGACY_FILES = {".DS_Store"}


@dataclass(frozen=True)
class StorageMapping:
    name: str
    source: Path
    dest: Path
    kind: str = "dir"
    compare_content: bool = True


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*") if path.is_file())


def tree_stats(root: Path) -> dict[str, int]:
    files = iter_files(root)
    return {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}


def planned_mappings(paths: StoragePaths) -> list[StorageMapping]:
    legacy = paths.root
    mappings = [
        StorageMapping("x raw", legacy / "x_threads" / "raw_api", paths.x_raw),
        StorageMapping("x records", legacy / "x_threads" / "thread_json", paths.x_records, compare_content=False),
        StorageMapping("x media", legacy / "x_threads" / "media", paths.x_media),
        StorageMapping("x descriptions", legacy / "x_threads" / "media_analysis", paths.x_descriptions),
        StorageMapping("x rendered pages", legacy / "x_threads" / "threads", paths.x_threads_html, compare_content=False),
        StorageMapping("presentation indexes", legacy / "x_threads" / "indexes", paths.indexes, compare_content=False),
        StorageMapping("x ignored", legacy / "x_threads" / "ignored", paths.x_ignored),
        StorageMapping("x rebuild", legacy / "x_threads" / "rebuild_staging", paths.x_rebuild),
        StorageMapping("x backups", legacy / "x_threads" / "cleanup_backups", paths.x_backups),
        StorageMapping("x usage", legacy / "x_threads" / "usage", paths.x_usage),
        StorageMapping("screenshots inbox", legacy / "manual_threads" / "inbox", paths.screenshots_inbox),
        StorageMapping("screenshots bundles", legacy / "manual_threads" / "bundles", paths.screenshots_bundles, compare_content=False),
        StorageMapping("screenshots media", legacy / "manual_threads" / "media", paths.screenshots_media),
        StorageMapping("prices daily", legacy / "market_prices" / "daily_ohlcv", paths.prices_daily),
        StorageMapping("prices manifest", legacy / "market_prices" / "manifest.json", paths.prices_manifest, "file", compare_content=False),
        StorageMapping("articles archive", legacy / "unsorted" / "AJ Investment Research PDFs", paths.articles_archive),
        StorageMapping("articles records", legacy / "hardcore" / "article_json", paths.articles_records, compare_content=False),
        StorageMapping("articles manifest", legacy / "hardcore" / "manifest.json", paths.articles_manifest, "file", compare_content=False),
        StorageMapping("legacy x evidence", legacy / "x_threads" / "evidence", paths.legacy_x_evidence),
        StorageMapping("legacy x vector manifest", legacy / "x_threads" / "vector_store_sync_manifest.json", paths.legacy_x_manifest, "file"),
        StorageMapping("legacy article evidence", legacy / "hardcore" / "evidence", paths.legacy_articles_evidence, compare_content=False),
        StorageMapping("workflow logs", legacy / "pipeline" / "logs", paths.workflow_logs),
        StorageMapping("workflow locks", legacy / "pipeline" / "locks", paths.workflow_locks),
        StorageMapping("workflow migrations", legacy / "pipeline" / "migrations", paths.workflow_migrations, compare_content=False),
        StorageMapping("legacy probes", legacy / "probes", paths.legacy_probes),
        StorageMapping("legacy unsorted", legacy / "unsorted", paths.legacy_unsorted),
    ]
    old_capture_root = legacy / "x_threads"
    if old_capture_root.exists():
        for path in sorted(old_capture_root.glob("20??-??-??")):
            if path.is_dir():
                mappings.append(StorageMapping(f"legacy old capture {path.name}", path, paths.legacy_old_captures / path.name))
    return mappings


def move_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            raise IsADirectoryError(f"Cannot replace directory with file: {dest}")
        dest.unlink()
    source.rename(dest)


def move_tree(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        target = dest / child.name
        if child.is_dir():
            move_tree(child, target)
        else:
            move_file(child, target)
    source.rmdir()


def move_path(source: Path, dest: Path) -> None:
    if source.is_dir():
        move_tree(source, dest)
    else:
        move_file(source, dest)


def relative_file_records(root: Path) -> list[dict[str, object]]:
    files = []
    for path in iter_files(root):
        relative = path.relative_to(root) if root.is_dir() else Path(path.name)
        files.append({"relative_path": str(relative), "bytes": path.stat().st_size, "sha256": file_sha256(path)})
    return files


def migrate_mapping(mapping: StorageMapping, apply: bool, verify_only: bool, data_root: Path) -> dict[str, object]:
    source = mapping.source
    dest = mapping.dest
    source_before = tree_stats(source)
    dest_before = tree_stats(dest)
    record: dict[str, object] = {
        "name": mapping.name,
        "kind": mapping.kind,
        "source": portable_path(source, data_root),
        "dest": portable_path(dest, data_root),
        "source_exists": source.exists(),
        "dest_exists": dest.exists(),
        "compare_content": mapping.compare_content,
        "status": "",
        "source_stats_before": source_before,
        "dest_stats_before": dest_before,
        "dest_stats_after": {},
        "files": [],
        "verified": True,
    }
    if apply and source.exists():
        move_path(source, dest)

    source_after_exists = source.exists()
    dest_after_exists = dest.exists()
    record["source_exists_after"] = source_after_exists
    record["dest_exists_after"] = dest_after_exists
    record["dest_stats_after"] = tree_stats(dest)
    record["files"] = relative_file_records(dest) if dest_after_exists else []

    source_existed = bool(record["source_exists"])
    if not source_after_exists and dest_after_exists:
        record["status"] = "migrated" if apply and source_existed else "already_migrated"
        record["verified"] = True
        return record
    if not source_after_exists and not dest_after_exists:
        record["status"] = "source_missing"
        record["verified"] = not source_existed
        return record
    if apply:
        record["status"] = "move_incomplete"
        record["verified"] = False
        return record
    record["status"] = "not_migrated" if verify_only else "planned_move"
    record["verified"] = not verify_only
    return record


def folder_readmes(paths: StoragePaths) -> dict[Path, str]:
    return {
        paths.root: """# Investment Tool Runtime Data

This folder contains local runtime data for the investment research pipeline. It is intentionally organized by source, context, presentation, retrieval, and workflow so a person or AI can inspect it without opening the code first.

Start with `sources` for original captured material, `context` for supporting data, `presentation` for readable HTML, and `workflow` for run logs.
""",
        paths.sources: """# Sources

Source folders contain captured or imported material before expensive AI analysis. Each child folder belongs to one input source family.

Use `x` for X API captures, `articles` for saved web article archives, and `screenshots` for manually provided screenshot threads.
""",
        paths.x_root: """# X Source

This folder contains X data for configured accounts. `raw` keeps saved API responses, `records` keeps clean thread records, and `media` keeps downloaded still images.

Generated records should describe the source account inside the file. Videos and animated GIFs are represented as skipped media placeholders rather than processed image evidence.
""",
        paths.articles_root: """# Articles Source

This folder contains saved article/archive input and normalized article records. Articles are supporting context for thread analysis and may be stale relative to later posts.

The current source may still be AJ/Hardcore/Ghost content, but reusable code should treat this as a generic saved-article source.
""",
        paths.screenshots_root: """# Screenshots Source

This folder contains manual screenshot inputs and reconstructed screenshot-thread bundles. Screenshots can represent threads that were not available through the X API.

Use `inbox` for new files, `bundles` for grouped screenshot-thread records, `media` for imported image files, and `records` for normalized outputs.
""",
        paths.context_root: """# Context

Context folders contain supporting data used to make analysis more accurate. This includes market prices and visual descriptions extracted from media.

Context should stay dated and source-aware so later AI passes can tell whether evidence was known at the time of a thread.
""",
        paths.prices_root: """# Prices

This folder contains USD-normalized market price history. `daily` is implemented now; `hourly` and `intraday` are planned for recent windows.

Price data is considered factual context and should be dated precisely when used in analysis.
""",
        paths.descriptions_root: """# Descriptions

This folder contains AI-generated visual descriptions for images. These descriptions let later text-only steps understand what screenshots and charts showed.

Descriptions should stay tied to the original media file and source folder; they are not standalone thread records.
""",
        paths.presentation_root: """# Presentation

This folder contains local readable views generated from canonical records. It is safe to regenerate from source records.

HTML pages and indexes should not be treated as authoritative source data.
""",
        paths.x_threads_html.parent: """# Thread Pages

This folder groups rendered thread pages by source. Current X pages live in `x`.

Rendered pages are for browsing and QA; source truth lives under `sources`.
""",
        paths.x_threads_html: """# X Thread Pages

This folder contains rendered HTML pages for X thread records. These files are regenerated by the render stage.

If a page looks wrong, inspect the matching JSON record in `sources/x/records` before trusting the HTML.
""",
        paths.indexes: """# Indexes

This folder contains browse indexes generated from canonical records. Indexes may include browser-only dynamic decorations such as current owned-coloring or relative time labels.

Indexes are presentation output and can be regenerated.
""",
        paths.retrieval_root: """# Retrieval

This folder contains vector/search memory outputs. Current vector sync code is legacy until the AI/vector design is finalized.

Do not treat legacy evidence files as final analysis unless the current spec says so.
""",
        paths.workflow_root: """# Workflow

This folder contains run logs and lock files. It should make recent runs auditable without needing a database.

Use `logs` for plain run logs and `locks` for stale-safe lock files.
""",
    }


def sync_folder_readmes(paths: StoragePaths, apply: bool) -> dict[str, object]:
    changed = 0
    missing_or_stale = 0
    for folder, body in folder_readmes(paths).items():
        readme = folder / "README.md"
        current = readme.read_text(encoding="utf-8") if readme.exists() else ""
        if current == body:
            continue
        missing_or_stale += 1
        if apply:
            folder.mkdir(parents=True, exist_ok=True)
            readme.write_text(body, encoding="utf-8")
            changed += 1
    if apply:
        missing_or_stale = 0
    return {
        "readmes": len(folder_readmes(paths)),
        "changed": changed,
        "missing_or_stale": missing_or_stale,
    }


def remove_empty_legacy_roots(paths: StoragePaths, apply: bool) -> dict[str, object]:
    candidates = [
        paths.root / "x_threads",
        paths.root / "manual_threads",
        paths.root / "market_prices",
        paths.root / "hardcore",
        paths.root / "pipeline",
        paths.root / "probes",
        paths.root / "unsorted",
    ]
    removed: list[str] = []
    removed_ignorable_files: list[str] = []
    remaining: list[str] = []
    for path in candidates:
        if not path.exists():
            continue
        if not path.is_dir():
            remaining.append(portable_path(path, paths.root))
            continue
        if apply:
            for child in path.iterdir():
                if child.is_file() and child.name in IGNORABLE_LEGACY_FILES:
                    child.unlink()
                    removed_ignorable_files.append(portable_path(child, paths.root))
        if any(path.iterdir()):
            remaining.append(portable_path(path, paths.root))
            continue
        if apply:
            path.rmdir()
            removed.append(portable_path(path, paths.root))
        else:
            remaining.append(portable_path(path, paths.root))
    return {"removed": removed, "removed_ignorable_files": removed_ignorable_files, "remaining": remaining}


def clean_old_targets(paths: StoragePaths) -> list[tuple[str, Path]]:
    return [
        ("moved legacy runtime junk", paths.legacy_root),
        ("old x rebuild staging", paths.x_rebuild),
        ("old x cleanup backups", paths.x_backups),
        ("legacy retrieval evidence", paths.legacy_retrieval_root),
    ]


def delete_path(path: Path) -> None:
    if path.is_dir():
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            delete_path(child)
        path.rmdir()
        return
    path.unlink()


def clean_old_storage(args: argparse.Namespace) -> int:
    paths = storage_paths(args.data_dir)
    apply = bool(args.apply)
    mode = "apply" if apply else "dry_run"
    targets: list[tuple[dict[str, object], Path]] = []
    for name, path in clean_old_targets(paths):
        exists = path.exists()
        stats = tree_stats(path)
        record = (
            {
                "name": name,
                "path": portable_path(path, paths.root),
                "exists": exists,
                "files": stats["files"],
                "bytes": stats["bytes"],
                "deleted": False,
            }
        )
        targets.append((record, path))
        if apply and exists:
            delete_path(path)
            record["deleted"] = True
    target_records = [record for record, _ in targets]
    deleted = [record for record, _ in targets if record["deleted"]]
    remaining = [record for record, path in targets if path.exists()]
    manifest = {
        "version": 1,
        "mode": mode,
        "generated_at": iso_now(),
        "data_root": portable_path(paths.root, paths.root),
        "summary": {
            "targets": len(target_records),
            "deleted": len(deleted),
            "remaining": len(remaining),
            "files_deleted": sum(int(item["files"]) for item in deleted),
            "bytes_deleted": sum(int(item["bytes"]) for item in deleted),
        },
        "targets": target_records,
    }
    manifest_path = paths.workflow_migrations / "storage_cleanup_manifest.json"
    if apply:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"STORAGE_CLEAN_OLD_MODE={mode}")
    print(f"DATA_ROOT={portable_path(paths.root, paths.root)}")
    print(f"TARGETS={manifest['summary']['targets']}")
    print(f"DELETED={manifest['summary']['deleted']}")
    print(f"REMAINING={manifest['summary']['remaining']}")
    print(f"FILES_DELETED={manifest['summary']['files_deleted']}")
    print(f"BYTES_DELETED={manifest['summary']['bytes_deleted']}")
    print(f"MANIFEST={portable_path(manifest_path, paths.root)}")
    return 1 if apply and remaining else 0


def path_replacements(paths: StoragePaths) -> list[tuple[str, str]]:
    root = paths.root
    repo = repo_root().resolve()
    pairs = [
        (root / "x_threads" / "raw_api", paths.x_raw),
        (root / "x_threads" / "media", paths.x_media),
        (root / "x_threads" / "thread_json", paths.x_records),
        (root / "x_threads" / "threads", paths.x_threads_html),
        (root / "x_threads" / "indexes", paths.indexes),
        (root / "x_threads" / "ignored", paths.x_ignored),
        (root / "x_threads" / "rebuild_staging", paths.x_rebuild),
        (root / "x_threads" / "cleanup_backups", paths.x_backups),
        (root / "x_threads" / "usage", paths.x_usage),
        (root / "x_threads" / "evidence", paths.legacy_x_evidence),
        (root / "x_threads" / "vector_store_sync_manifest.json", paths.legacy_x_manifest),
        (root / "manual_threads" / "inbox", paths.screenshots_inbox),
        (root / "manual_threads" / "media", paths.screenshots_media),
        (root / "manual_threads" / "bundles", paths.screenshots_bundles),
        (root / "market_prices" / "daily_ohlcv", paths.prices_daily),
        (root / "market_prices" / "manifest.json", paths.prices_manifest),
        (root / "hardcore" / "article_json", paths.articles_records),
        (root / "hardcore" / "evidence", paths.legacy_articles_evidence),
        (root / "hardcore" / "manifest.json", paths.articles_manifest),
        (root / "hardcore", paths.articles_root),
        (root / "pipeline" / "logs", paths.workflow_logs),
        (root / "pipeline" / "locks", paths.workflow_locks),
        (root / "pipeline" / "migrations", paths.workflow_migrations),
        (root / "unsorted" / "AJ Investment Research PDFs", paths.articles_archive),
        (root, Path(DATA_TOKEN)),
        (repo, Path(REPO_TOKEN)),
    ]
    replacements: list[tuple[str, str]] = []
    for old, new in pairs:
        new_text = str(new)
        if not new_text.startswith((DATA_TOKEN, REPO_TOKEN)):
            new_text = portable_path(new, paths.root)
        replacements.append((str(old), new_text))
    return replacements


def replace_string_prefix(value: str, replacements: list[tuple[str, str]]) -> str:
    for old, new in replacements:
        if value.startswith(old):
            return new + value[len(old) :]
    return value


def replace_json_paths(value: object, replacements: list[tuple[str, str]]) -> object:
    if isinstance(value, str):
        return replace_string_prefix(value, replacements)
    if isinstance(value, list):
        return [replace_json_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: replace_json_paths(item, replacements) for key, item in value.items()}
    return value


def canonicalize_json_file(path: Path, replacements: list[tuple[str, str]], apply: bool) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    updated = replace_json_paths(data, replacements)
    if updated == data:
        return False
    if apply:
        path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def canonicalize_text_file(path: Path, replacements: list[tuple[str, str]], apply: bool) -> bool:
    try:
        original = path.read_text(encoding="utf-8")
    except Exception:
        return False
    updated = original
    for old, new in replacements:
        updated = updated.replace(old, new)
    if updated == original:
        return False
    if apply:
        path.write_text(updated, encoding="utf-8")
    return True


def canonicalizable_files(paths: StoragePaths) -> tuple[list[Path], list[Path]]:
    json_files = [
        path
        for folder in (paths.sources, paths.context_root, paths.retrieval_root, paths.workflow_root)
        for path in iter_files(folder)
        if path.suffix.lower() == ".json"
    ]
    text_files = [
        path
        for folder in (paths.presentation_root, paths.retrieval_root, paths.workflow_root)
        for path in iter_files(folder)
        if path.suffix.lower() in {".html", ".log", ".md", ".txt"}
    ]
    return json_files, text_files


def count_stale_path_references(paths: StoragePaths, replacements: list[tuple[str, str]]) -> int:
    old_values = [old for old, _ in replacements]
    json_files, text_files = canonicalizable_files(paths)
    scan_files = json_files + text_files
    stale = 0
    for path in scan_files:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if any(old in text for old in old_values):
            stale += 1
    return stale


def canonicalize_runtime_paths(paths: StoragePaths, apply: bool) -> dict[str, object]:
    replacements = path_replacements(paths)
    json_files, text_files = canonicalizable_files(paths)
    changed_json = sum(1 for path in json_files if canonicalize_json_file(path, replacements, apply))
    changed_text = sum(1 for path in text_files if canonicalize_text_file(path, replacements, apply))
    stale_refs = count_stale_path_references(paths, replacements)

    def display_value(value: str) -> str:
        path = Path(value).expanduser()
        return portable_path(path, paths.root) if path.is_absolute() else value

    return {
        "mode": "apply" if apply else "check",
        "json_files_scanned": len(json_files),
        "text_files_scanned": len(text_files),
        "json_files_changed": changed_json,
        "text_files_changed": changed_text,
        "stale_path_reference_files": stale_refs,
        "replacements": [{"old": display_value(old), "new": display_value(new)} for old, new in replacements],
    }


def migrate_storage(args: argparse.Namespace) -> int:
    paths = storage_paths(args.data_dir)
    apply = bool(args.apply)
    verify_only = bool(args.verify_only)
    if apply:
        paths.ensure_runtime_dirs(include_planned=False)
    mode = "apply" if apply else ("verify_only" if verify_only else "dry_run")
    mappings = planned_mappings(paths)
    results = [migrate_mapping(mapping, apply=apply, verify_only=verify_only, data_root=paths.root) for mapping in mappings]
    canonicalization = canonicalize_runtime_paths(paths, apply=apply) if (apply or verify_only) else {}
    readmes = sync_folder_readmes(paths, apply=apply) if (apply or verify_only) else {}
    legacy_roots = remove_empty_legacy_roots(paths, apply=apply) if apply else remove_empty_legacy_roots(paths, apply=False)
    failed = [item for item in results if (apply or verify_only) and item["source_exists"] and not item["verified"]]
    stale_refs = int(canonicalization.get("stale_path_reference_files") or 0)
    readme_failures = int(readmes.get("missing_or_stale") or 0)
    manifest = {
        "version": 1,
        "mode": mode,
        "generated_at": iso_now(),
        "data_root": portable_path(paths.root, paths.root),
        "target_layout": "canonical_storage_v1",
        "summary": {
            "mappings": len(results),
            "planned_moves": sum(1 for item in results if item["status"] == "planned_move"),
            "migrated": sum(1 for item in results if item["status"] == "migrated"),
            "already_migrated": sum(1 for item in results if item["status"] == "already_migrated"),
            "source_missing": sum(1 for item in results if item["status"] == "source_missing"),
            "verified": sum(1 for item in results if item["verified"]),
            "failed": len(failed) + stale_refs + readme_failures,
            "stale_path_reference_files": stale_refs,
            "readme_missing_or_stale": readme_failures,
            "empty_legacy_roots_removed": len(legacy_roots.get("removed", [])),
            "legacy_roots_remaining": len(legacy_roots.get("remaining", [])),
        },
        "mappings": results,
        "canonicalization": canonicalization,
        "folder_readmes": readmes,
        "legacy_root_cleanup": legacy_roots,
    }
    manifest_path = resolve_portable_path(args.manifest) if args.manifest else paths.storage_migration_manifest
    if apply or verify_only:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"STORAGE_MIGRATION_MODE={mode}")
    print(f"DATA_ROOT={portable_path(paths.root, paths.root)}")
    print(f"MAPPINGS={manifest['summary']['mappings']}")
    print(f"PLANNED_MOVES={manifest['summary']['planned_moves']}")
    print(f"MIGRATED={manifest['summary']['migrated']}")
    print(f"ALREADY_MIGRATED={manifest['summary']['already_migrated']}")
    print(f"SOURCE_MISSING={manifest['summary']['source_missing']}")
    print(f"VERIFIED={manifest['summary']['verified']}")
    print(f"FAILED={manifest['summary']['failed']}")
    print(f"STALE_PATH_REFERENCE_FILES={manifest['summary']['stale_path_reference_files']}")
    print(f"README_MISSING_OR_STALE={manifest['summary']['readme_missing_or_stale']}")
    print(f"EMPTY_LEGACY_ROOTS_REMOVED={manifest['summary']['empty_legacy_roots_removed']}")
    print(f"LEGACY_ROOTS_REMAINING={manifest['summary']['legacy_roots_remaining']}")
    print(f"MANIFEST={portable_path(manifest_path, paths.root)}")
    if failed:
        for item in failed[:20]:
            print(f"VERIFY_FAILED name={item['name']} source={item['source']} dest={item['dest']}", file=sys.stderr)
    return 1 if failed or stale_refs or readme_failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runtime storage maintenance.")
    subparsers = parser.add_subparsers(dest="command")
    migrate = subparsers.add_parser("migrate", help="Rename/move and verify runtime data into canonical storage folders.")
    mode = migrate.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Show the migration plan without writing files.")
    mode.add_argument("--apply", action="store_true", help="Move data into the canonical storage layout.")
    mode.add_argument("--verify-only", action="store_true", help="Verify an already-moved canonical layout.")
    migrate.add_argument("--data-dir", default="", help="Runtime data root. Defaults to INVESTMENT_TOOL_DATA_DIR, then INVESTMENT_TOOL_HOME/data, then repo-local data/.")
    migrate.add_argument("--manifest", default="", help="Override migration manifest path.")
    clean_old = subparsers.add_parser("clean-old", help="Delete obsolete migrated legacy folders after verification.")
    clean_mode = clean_old.add_mutually_exclusive_group(required=True)
    clean_mode.add_argument("--dry-run", action="store_true", help="Show old folders that would be deleted.")
    clean_mode.add_argument("--apply", action="store_true", help="Delete old migrated folders and files.")
    clean_old.add_argument("--data-dir", default="", help="Runtime data root. Defaults to INVESTMENT_TOOL_DATA_DIR, then INVESTMENT_TOOL_HOME/data, then repo-local data/.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "migrate":
        return migrate_storage(args)
    if args.command == "clean-old":
        return clean_old_storage(args)
    parser.print_help()
    return 0
