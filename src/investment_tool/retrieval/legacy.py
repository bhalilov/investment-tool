#!/usr/bin/env python3
"""Generate thread evidence docs and sync them into an OpenAI vector store.

This script is intentionally separate from capture_threads.py:

- X capture owns collecting local thread records only.
- this script owns converting those records into searchable evidence docs and
  attaching them to an OpenAI Platform vector store.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from investment_tool.analysis.openai import OPENAI_API_BASE, request_json as openai_request_json
from investment_tool.runtime.env import load_env
from investment_tool.runtime.config import FeedProfile, load_x_feed_profile, feed_identity, feed_label
from investment_tool.runtime.paths import portable_path, resolve_portable_path, storage_paths
from investment_tool.runtime.reporting import start_reporter


DEFAULT_PUBLIC_BASE_URL = "http://localhost:8787"
FEED_PROFILE: FeedProfile = load_x_feed_profile()
FEED_USERNAME = FEED_PROFILE.username
FEED_USER_ID = FEED_PROFILE.user_id


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_stem(value: str, fallback: str = "thread") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:180] or fallback


def display_text(tweet: dict[str, Any]) -> str:
    note_text = ((tweet.get("note_tweet") or {}).get("text") or "").strip()
    if note_text:
        return note_text
    return tweet.get("text") or ""


def tweet_url(tweet_id: str) -> str:
    return f"https://x.com/{FEED_USERNAME}/status/{tweet_id}"


def configure_feed(profile: FeedProfile) -> None:
    global FEED_PROFILE, FEED_USERNAME, FEED_USER_ID
    FEED_PROFILE = profile
    FEED_USERNAME = profile.username
    FEED_USER_ID = profile.user_id


def record_feed_identity(record: dict[str, Any]) -> dict[str, Any]:
    feed = record.get("feed") if isinstance(record.get("feed"), dict) else {}
    feed = feed if isinstance(feed, dict) else {}
    return {**feed_identity(FEED_PROFILE), **feed}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def markdown_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```"
    return clean_text(value)


def web_join(base_url: str, *parts: str) -> str:
    base = base_url.rstrip("/")
    clean_parts = [urllib.parse.quote(part.strip("/")) for part in parts if part]
    return "/".join([base] + clean_parts)


def evidence_filename(record: dict[str, Any], record_path: Path) -> str:
    created_at = str(record.get("created_at") or "")
    date = created_at[:10].replace("-", "") if len(created_at) >= 10 else record_path.name[:8]
    primary_ticker = str(record.get("primary_ticker") or "UNKNOWN").upper()
    thread_id = str(record.get("conversation_id") or record_path.stem.split("__")[-1])
    title = clean_text(record.get("title")) or record_path.stem
    topic = safe_stem(title.lower(), "thread")
    return f"{date}__{primary_ticker}__{topic}__{thread_id}.md"


def first_feed_tweet_id(record: dict[str, Any]) -> str:
    conversation_id = str(record.get("conversation_id") or "")
    tweets = as_list(record.get("tweets"))
    for tweet in tweets:
        if str(tweet.get("id") or "") == conversation_id:
            return conversation_id
    for tweet in sorted(tweets, key=lambda item: str(item.get("created_at") or "")):
        if str(tweet.get("author_id") or "") == FEED_USER_ID and tweet.get("id"):
            return str(tweet["id"])
    return conversation_id


def media_urls(record: dict[str, Any], public_base_url: str) -> list[str]:
    urls: list[str] = []
    wanted_keys: set[str] = set()
    for tweet in as_list(record.get("tweets")):
        attachments = tweet.get("attachments") or {}
        wanted_keys.update(str(key) for key in attachments.get("media_keys") or [])
    media_paths = record.get("media_paths") or {}
    if isinstance(media_paths, dict):
        items = media_paths.items()
        if wanted_keys:
            items = [(key, value) for key, value in items if str(key) in wanted_keys]
        for _, value in items:
            path = resolve_portable_path(str(value))
            if path.name:
                urls.append(web_join(public_base_url, "media", path.name))
    return list(dict.fromkeys(urls))


def thread_metadata(record: dict[str, Any], record_path: Path) -> dict[str, str | int | float | bool]:
    feed = record_feed_identity(record)
    tickers = [str(item).upper() for item in as_list(record.get("tickers")) if str(item).strip()]
    primary_ticker = str(record.get("primary_ticker") or "UNKNOWN").upper()
    title = clean_text(record.get("title")) or record_path.stem
    created_at = str(record.get("created_at") or "")
    thread_date = created_at[:10] if len(created_at) >= 10 else record_path.name[:8]
    if re.fullmatch(r"\d{8}", thread_date):
        thread_date = f"{thread_date[:4]}-{thread_date[4:6]}-{thread_date[6:8]}"
    media_paths = record.get("media_paths") or {}
    has_media = bool(media_paths) or bool(record.get("media"))
    has_ocr = bool(record.get("ocr_text") or record.get("ocr") or record.get("ocr_needed"))
    priority = str(record.get("priority") or "")
    category = str(record.get("category") or "")
    noise = primary_ticker == "UNKNOWN" and priority in {"P3", "P4"} and category in {"RANT", "BRAG", "SELF_PROMO", "OFF_TOPIC"}
    return {
        "feed_type": "x_thread",
        "feed_id": str(feed.get("feed_id") or "")[:128],
        "feed_platform": str(feed.get("platform") or "")[:64],
        "feed_username": str(feed.get("username") or "")[:128],
        "feed_user_id": str(feed.get("user_id") or "")[:128],
        "thread_id": str(record.get("conversation_id") or record_path.stem.split("__")[-1]),
        "content_type": "evidence_thread",
        "primary_ticker": primary_ticker[:64],
        "tickers": ",".join(tickers)[:512],
        "date": thread_date[:64],
        "has_ocr": has_ocr,
        "has_media": has_media,
        "noise": noise,
        "category": category[:64],
        "signal": str(record.get("signal") or "")[:64],
        "stance": str(record.get("stance") or "")[:64],
        "priority": priority[:64],
        "title": title[:512],
    }


def render_thread_markdown(record: dict[str, Any], record_path: Path, public_base_url: str) -> str:
    metadata = thread_metadata(record, record_path)
    thread_id = str(metadata["thread_id"])
    feed_tweet_id = first_feed_tweet_id(record)
    canonical_filename = str(record.get("canonical_filename") or "")
    captured_html_url = web_join(public_base_url, "threads", canonical_filename) if canonical_filename else ""
    evidence_url = web_join(public_base_url, "evidence", evidence_filename(record, record_path))
    urls = media_urls(record, public_base_url)
    feed = record_feed_identity(record)
    lines: list[str] = []
    title = metadata["title"]
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Feed Profile ID: {feed.get('feed_id') or ''}")
    lines.append(f"Feed Platform: {feed.get('platform') or ''}")
    lines.append(f"Feed Account: @{feed.get('username') or ''}")
    lines.append(f"Feed User ID: {feed.get('user_id') or ''}")
    lines.append(f"Feed Display Name: {feed.get('display_name') or ''}")
    lines.append(f"Feed X URL: {tweet_url(feed_tweet_id) if feed_tweet_id else ''}")
    lines.append(f"Captured HTML URL: {captured_html_url}")
    lines.append(f"Evidence URL: {evidence_url}")
    lines.append(f"Captured Date: {metadata['date']}")
    lines.append(f"Feed Type: {metadata['feed_type']}")
    lines.append(f"Thread ID: {thread_id}")
    lines.append(f"Primary Ticker: {metadata['primary_ticker']}")
    lines.append(f"Tickers: {metadata['tickers']}")
    lines.append(f"Noise: {str(metadata['noise']).lower()}")
    lines.append(f"Has OCR: {str(metadata['has_ocr']).lower()}")
    lines.append(f"Has Media: {str(metadata['has_media']).lower()}")
    lines.append(f"Category: {metadata['category']}")
    lines.append(f"Signal: {metadata['signal']}")
    lines.append(f"Stance: {metadata['stance']}")
    lines.append(f"Priority: {metadata['priority']}")

    tldr = clean_text(record.get("tldr"))
    if tldr:
        lines.extend(["", "## Thread Summary", tldr])

    analysis = markdown_value(record.get("analysis"))
    if analysis:
        lines.extend(["", "## Analysis", analysis])

    for heading, key in (
        ("Evidence", "evidence"),
        ("Ambiguities", "ambiguities"),
        ("Contradiction Flags", "contradiction_flags"),
        ("Flags", "flags"),
        ("Tags", "tags"),
        ("Context Tickers", "context_tickers"),
        ("Mentioned Only Tickers", "mentioned_only_tickers"),
    ):
        values = [clean_text(item) for item in as_list(record.get(key)) if clean_text(item)]
        if values:
            lines.extend(["", f"## {heading}"])
            lines.extend(f"- {item}" for item in values)

    tweets = sorted(
        as_list(record.get("tweets")),
        key=lambda item: str(item.get("created_at") or ""),
    )
    users = record.get("users") or {}
    feed_tweets = [tweet for tweet in tweets if str(tweet.get("author_id") or "") == FEED_USER_ID]
    other_tweets = [tweet for tweet in tweets if str(tweet.get("author_id") or "") != FEED_USER_ID]
    if feed_tweets:
        lines.extend(["", "## Feed Posts"])
    for tweet in feed_tweets:
        tweet_id = str(tweet.get("id") or "")
        created_at = tweet.get("created_at") or ""
        text = clean_text(display_text(tweet))
        lines.extend(
            [
                "",
                f"### {created_at}",
                f"Post URL: {tweet_url(tweet_id) if tweet_id else ''}",
                "Text:",
                text,
            ]
        )

    if other_tweets:
        lines.extend(["", "## Questions Feed Answered"])
    for tweet in other_tweets:
        tweet_id = str(tweet.get("id") or "")
        author_id = str(tweet.get("author_id") or "")
        user = users.get(author_id) if isinstance(users, dict) else None
        username = (user or {}).get("username") or author_id or "unknown"
        text = clean_text(display_text(tweet))
        if not text:
            continue
        lines.extend(
            [
                "",
                "### Question / Context",
                f"Author: @{username}",
                f"Post URL: {tweet_url(tweet_id) if tweet_id else ''}",
                "Text:",
                text,
            ]
        )

    if urls:
        lines.extend(["", "## Screenshots And OCR"])
        for index, url in enumerate(urls, 1):
            lines.extend(["", f"### Media {index}", f"Media URL: {url}", "OCR Text:", ""])

    linked = as_list(record.get("linked_context")) + as_list(record.get("linked_context_required"))
    if linked:
        lines.extend(["", "## Linked Context"])
        lines.extend(f"- {clean_text(item)}" for item in linked if clean_text(item))

    lines.extend(
        [
            "",
            "## Analyst Notes",
            f"- Possible action signal: {record.get('signal') or ''}",
            "- Contradictions:",
            *[f"  - {item}" for item in as_list(record.get("contradiction_flags")) if clean_text(item)],
            "- Changed thesis:",
            "- Open questions:",
            *[f"  - {item}" for item in as_list(record.get("ambiguities")) if clean_text(item)],
        ]
    )

    return "\n".join(lines).strip() + "\n"


def render_thread_json(record: dict[str, Any], record_path: Path) -> str:
    """Render a compact JSON document for users who prefer exact structured uploads."""
    tweets = []
    users = record.get("users") or {}
    for tweet in sorted(as_list(record.get("tweets")), key=lambda item: str(item.get("created_at") or "")):
        tweet_id = str(tweet.get("id") or "")
        author_id = str(tweet.get("author_id") or "")
        user = users.get(author_id) if isinstance(users, dict) else None
        tweets.append(
            {
                "id": tweet_id,
                "author": (user or {}).get("username") or author_id or "unknown",
                "created_at": tweet.get("created_at"),
                "url": tweet_url(tweet_id) if tweet_id else "",
                "text": clean_text(display_text(tweet)),
                "public_metrics": tweet.get("public_metrics") or {},
            }
        )
    document = {
        "metadata": thread_metadata(record, record_path),
        "tldr": clean_text(record.get("tldr")),
        "analysis": clean_text(record.get("analysis")),
        "evidence": as_list(record.get("evidence")),
        "ambiguities": as_list(record.get("ambiguities")),
        "contradiction_flags": as_list(record.get("contradiction_flags")),
        "flags": as_list(record.get("flags")),
        "tags": as_list(record.get("tags")),
        "media_paths": record.get("media_paths") or {},
        "tweets": tweets,
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render_thread_document(record: dict[str, Any], record_path: Path, public_base_url: str) -> str:
    return render_thread_markdown(record, record_path, public_base_url)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "vector_store_id": "", "threads": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "vector_store_id": "", "threads": {}}
    data.setdefault("version", 1)
    data.setdefault("vector_store_id", "")
    data.setdefault("threads", {})
    return data


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


class OpenAIClient:
    def __init__(self, api_key: str, api_base: str = OPENAI_API_BASE) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return openai_request_json(
            method,
            path,
            api_key=self.api_key,
            body=body,
            headers=headers,
            timeout=60,
            api_base=self.api_base,
        )

    def create_vector_store(self, name: str) -> str:
        data = self.request("POST", "/vector_stores", {"name": name})
        vector_store_id = data.get("id")
        if not vector_store_id:
            raise RuntimeError(f"Create vector store response did not include id: {data}")
        return str(vector_store_id)

    def upload_file(self, path: Path, purpose: str = "assistants") -> str:
        fields = {"purpose": purpose}
        files = {"file": path}
        data, content_type = encode_multipart(fields, files)
        req = urllib.request.Request(
            self.api_base + "/files",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": content_type,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI file upload failed with {exc.code}: {raw[:1000]}") from exc
        response = json.loads(raw)
        file_id = response.get("id")
        if not file_id:
            raise RuntimeError(f"File upload response did not include id: {response}")
        return str(file_id)

    def attach_file_to_vector_store(
        self,
        vector_store_id: str,
        file_id: str,
        attributes: dict[str, str | int | float | bool],
    ) -> str:
        response = self.request(
            "POST",
            f"/vector_stores/{urllib.parse.quote(vector_store_id)}/files",
            {
                "file_id": file_id,
                "attributes": trim_attributes(attributes),
            },
        )
        attached_file_id = response.get("id") or file_id
        return str(attached_file_id)

    def delete_vector_store_file(self, vector_store_id: str, file_id: str) -> None:
        self.request(
            "DELETE",
            f"/vector_stores/{urllib.parse.quote(vector_store_id)}/files/{urllib.parse.quote(file_id)}",
        )

    def delete_file(self, file_id: str) -> None:
        self.request("DELETE", f"/files/{urllib.parse.quote(file_id)}")


def trim_attributes(attributes: dict[str, Any]) -> dict[str, str | int | float | bool]:
    trimmed: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        if len(trimmed) >= 16:
            break
        key_text = str(key)[:64]
        if isinstance(value, (bool, int, float)):
            trimmed[key_text] = value
        else:
            trimmed[key_text] = str(value)[:512]
    return trimmed


def encode_multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----investment-tool-" + hashlib.sha1(os.urandom(16)).hexdigest()
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for key, path in files.items():
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{key}"; '
                    f'filename="{path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def iter_thread_paths(thread_json_dir: Path) -> list[Path]:
    return sorted(path for path in thread_json_dir.glob("*.json") if path.is_file())


def generate_evidence_documents(args: argparse.Namespace) -> tuple[int, int, int]:
    thread_json_dir = resolve_portable_path(args.thread_json_dir)
    evidence_dir = resolve_portable_path(args.evidence_dir)
    paths = iter_thread_paths(thread_json_dir)
    if args.limit:
        paths = paths[: args.limit]

    written = 0
    unchanged = 0
    failed = 0
    if not args.dry_run:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            document = render_thread_document(record, path, args.public_base_url)
            out_path = evidence_dir / evidence_filename(record, path)
            if out_path.exists() and out_path.read_text(encoding="utf-8") == document:
                unchanged += 1
                continue
            if args.dry_run:
                print(f"Would write evidence: {out_path}")
            else:
                out_path.write_text(document, encoding="utf-8")
            written += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR: Failed to generate evidence from {path}: {exc}", file=sys.stderr)
            if args.stop_on_error:
                break
    return written, unchanged, failed


def evidence_metadata(path: Path) -> dict[str, str | int | float | bool]:
    metadata: dict[str, str | int | float | bool] = {
        "feed_type": "x_thread",
        "content_type": "evidence_thread",
        "thread_id": "",
        "date": "",
        "primary_ticker": "UNKNOWN",
        "tickers": "",
        "has_ocr": False,
        "has_media": False,
        "noise": False,
    }
    header = path.read_text(encoding="utf-8")[:6000]
    key_map = {
        "Captured Date": "date",
        "Feed Type": "feed_type",
        "Thread ID": "thread_id",
        "Primary Ticker": "primary_ticker",
        "Tickers": "tickers",
        "Category": "category",
        "Signal": "signal",
        "Stance": "stance",
        "Priority": "priority",
    }
    for line in header.splitlines():
        if ": " not in line:
            continue
        raw_key, raw_value = line.split(": ", 1)
        key = key_map.get(raw_key.strip())
        if key:
            metadata[key] = raw_value.strip()[:512]
        elif raw_key == "Has OCR":
            metadata["has_ocr"] = raw_value.strip().lower() == "true"
        elif raw_key == "Has Media":
            metadata["has_media"] = raw_value.strip().lower() == "true"
        elif raw_key == "Noise":
            metadata["noise"] = raw_value.strip().lower() == "true"
    if path.name[:8].isdigit() and not metadata.get("date"):
        metadata["date"] = f"{path.name[:4]}-{path.name[4:6]}-{path.name[6:8]}"
    return metadata


def iter_evidence_paths(evidence_dir: Path) -> list[Path]:
    return sorted(path for path in evidence_dir.glob("*.md") if path.is_file())


def sync_threads(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file).expanduser()
    load_env(env_path)
    configure_feed(load_x_feed_profile(args.feed_config, args.feed_id))
    storage = storage_paths()
    if not args.thread_json_dir:
        args.thread_json_dir = str(storage.x_records)
    if not args.evidence_dir:
        args.evidence_dir = str(storage.legacy_x_evidence)
    if not args.manifest:
        args.manifest = str(storage.legacy_x_manifest)
    if not args.public_base_url:
        args.public_base_url = (
            os.environ.get("INVESTMENT_TOOL_PUBLIC_BASE_URL")
            or DEFAULT_PUBLIC_BASE_URL
        )
    if not args.vector_store_name:
        args.vector_store_name = f"{feed_label(FEED_PROFILE)} X Threads"
    evidence_dir = resolve_portable_path(args.evidence_dir)
    manifest_path = resolve_portable_path(args.manifest)
    initial_paths = iter_evidence_paths(evidence_dir)
    planned_total = len(initial_paths)
    if not args.upload_only:
        planned_total = len(iter_thread_paths(resolve_portable_path(args.thread_json_dir)))
        if args.limit:
            planned_total = min(planned_total, args.limit)
    reporter = start_reporter(
        "vector_store_sync",
        total=planned_total,
        every_items=10,
        every_seconds=30,
        mode="dry_run" if args.dry_run else "sync",
        generate_only=str(args.generate_only).lower(),
        upload_only=str(args.upload_only).lower(),
        force=str(args.force).lower(),
        evidence_dir=portable_path(evidence_dir),
        manifest=portable_path(manifest_path),
        evidence_files=len(initial_paths),
        openai_usage_available="file_counts_only",
    )
    gen_written = gen_unchanged = gen_failed = 0
    if not args.upload_only:
        gen_written, gen_unchanged, gen_failed = generate_evidence_documents(args)
        reporter.checkpoint(
            force=True,
            phase="evidence_generation",
            written=gen_written,
            unchanged=gen_unchanged,
            failed=gen_failed,
        )
        if args.generate_only:
            reporter.done(
                generated_written=gen_written,
                generated_unchanged=gen_unchanged,
                generated_failed=gen_failed,
                uploaded=0,
                skipped=0,
                failed=gen_failed,
                manifest=portable_path(manifest_path),
            )
            return 1 if gen_failed else 0

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print("ERROR: OPENAI_API_KEY is required. Put it in .env or export it.", file=sys.stderr)
        reporter.fail(error="missing_openai_api_key")
        return 2

    manifest = load_manifest(manifest_path)
    vector_store_id = args.vector_store_id or os.environ.get("OPENAI_VECTOR_STORE_ID", "").strip()
    if not vector_store_id:
        vector_store_id = str(manifest.get("vector_store_id") or "")

    client = OpenAIClient(api_key) if api_key else None
    if not vector_store_id:
        if args.dry_run:
            vector_store_id = "dry-run-vector-store"
        elif args.create:
            assert client is not None
            vector_store_id = client.create_vector_store(args.vector_store_name)
            reporter.checkpoint(force=True, phase="vector_store_created", vector_store_id=vector_store_id)
        else:
            print(
                "ERROR: Set OPENAI_VECTOR_STORE_ID, pass --vector-store-id, or use --create.",
                file=sys.stderr,
            )
            reporter.fail(error="missing_vector_store_id")
            return 2

    manifest["vector_store_id"] = vector_store_id
    evidence_records = manifest.setdefault("evidence", {})
    paths = iter_evidence_paths(evidence_dir)
    if args.latest:
        paths = list(reversed(paths))
    if args.limit:
        paths = paths[: args.limit]

    stats = {
        "changed": 0,
        "skipped": 0,
        "failed": 0,
        "uploaded": 0,
    }

    def processed_count() -> int:
        return stats["changed"] + stats["skipped"] + stats["failed"]

    for path in paths:
        try:
            document = path.read_text(encoding="utf-8")
            content_hash = sha256_text(document)
            key = path.name
            previous = evidence_records.get(key) or {}
            if not args.force and previous.get("content_hash") == content_hash:
                stats["skipped"] += 1
                continue

            stats["changed"] += 1
            metadata = evidence_metadata(path)
            if args.dry_run:
                reporter.checkpoint_stats(stats, processed=processed_count(), path=path.name, dry_run_upload="true")
                continue

            assert client is not None
            new_file_id = client.upload_file(path)
            vector_file_id = client.attach_file_to_vector_store(vector_store_id, new_file_id, metadata)

            old_file_id = previous.get("file_id")
            if old_file_id and old_file_id != new_file_id and not args.keep_old_files:
                try:
                    client.delete_vector_store_file(vector_store_id, str(old_file_id))
                except Exception as exc:
                    print(f"WARN: Could not remove old vector-store file {old_file_id}: {exc}", file=sys.stderr)
                try:
                    client.delete_file(str(old_file_id))
                except Exception as exc:
                    print(f"WARN: Could not delete old OpenAI file {old_file_id}: {exc}", file=sys.stderr)

            evidence_records[key] = {
                "content_hash": content_hash,
                "file_id": new_file_id,
                "vector_store_file_id": vector_file_id,
                "evidence_path": portable_path(path),
                "thread_id": metadata.get("thread_id", ""),
                "primary_ticker": metadata.get("primary_ticker", ""),
                "date": metadata.get("date", ""),
                "synced_at": iso_now(),
            }
            stats["uploaded"] += 1
            if stats["uploaded"] % 10 == 0:
                save_manifest(manifest_path, manifest)
            reporter.checkpoint_stats(
                stats,
                processed=processed_count(),
                path=path.name,
            )
        except Exception as exc:
            stats["failed"] += 1
            print(f"ERROR: Failed to sync {path}: {exc}", file=sys.stderr)
            reporter.checkpoint_stats(stats, processed=processed_count(), force=True, path=path.name)
            if args.stop_on_error:
                break

    if not args.dry_run:
        manifest["generated_at"] = iso_now() if gen_written else manifest.get("generated_at", "")
        manifest["updated_at"] = iso_now()
        save_manifest(manifest_path, manifest)

    if args.dry_run:
        print("Dry run only; no files were uploaded and the manifest was not updated.")
    reporter.done(
        vector_store_id=vector_store_id,
        generated_written=gen_written,
        generated_unchanged=gen_unchanged,
        generated_failed=gen_failed,
        **stats,
        dry_run=str(args.dry_run).lower(),
        manifest=portable_path(manifest_path),
    )
    return 1 if stats["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync captured X feed threads into an OpenAI vector store.")
    parser.add_argument("--feed-config", default="config/feeds/x_accounts.json")
    parser.add_argument("--feed-id", default="")
    parser.add_argument("--thread-json-dir", default="")
    parser.add_argument("--evidence-dir", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--vector-store-id", default="")
    parser.add_argument("--vector-store-name", default="")
    parser.add_argument("--public-base-url", default="")
    parser.add_argument("--create", action="store_true", help="Create a vector store when no ID is configured.")
    parser.add_argument("--generate-only", action="store_true", help="Generate evidence docs without uploading.")
    parser.add_argument("--upload-only", action="store_true", help="Upload existing evidence docs without regenerating.")
    parser.add_argument("--force", action="store_true", help="Upload every thread even if unchanged.")
    parser.add_argument("--keep-old-files", action="store_true", help="Keep old OpenAI files after changed uploads.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would sync without calling OpenAI.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of thread JSON files processed.")
    parser.add_argument("--latest", action="store_true", help="Process newest evidence files first.")
    parser.add_argument("--stop-on-error", action="store_true")
    return sync_threads(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
