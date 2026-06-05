#!/usr/bin/env python3
"""Local Custom GPT Action backend for investment evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from investment_tool.runtime.env import load_env
from investment_tool.runtime.config import SourceProfile, load_x_source_profile
from investment_tool.runtime.paths import portable_path, resolve_portable_path, storage_paths
from investment_tool.runtime.reporting import start_reporter


DEFAULT_PUBLIC_BASE_URL = "http://localhost:8787"
DEFAULT_PORT = 8787
SOURCE_PROFILE: SourceProfile = load_x_source_profile()
SOURCE_USERNAME = SOURCE_PROFILE.username


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def tweet_url(tweet_id: str) -> str:
    return f"https://x.com/{SOURCE_USERNAME}/status/{tweet_id}"


def configure_source(profile: SourceProfile) -> None:
    global SOURCE_PROFILE, SOURCE_USERNAME
    SOURCE_PROFILE = profile
    SOURCE_USERNAME = profile.username


def normalize_api_path(path: str) -> str:
    for prefix in ("/source", "/aj"):
        if path == prefix:
            return "/"
        if path.startswith(f"{prefix}/"):
            return path.removeprefix(prefix)
    return path


def legacy_evidence_headings(kind: str) -> list[str]:
    headings = SOURCE_PROFILE.user_specifics.get("legacy_evidence_headings") or {}
    values = headings.get(kind) if isinstance(headings, dict) else []
    return [str(item) for item in values or [] if str(item)]


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def web_join(base_url: str, *parts: str) -> str:
    base = base_url.rstrip("/")
    clean_parts = [urllib.parse.quote(part.strip("/")) for part in parts if part]
    return "/".join([base] + clean_parts)


def parse_frontmatterish_markdown(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0].removeprefix("# ").strip() if lines else path.stem
    data: dict[str, Any] = {
        "title": title,
        "evidence_path": portable_path(path),
        "evidence_markdown": text,
        "evidence_excerpt": excerpt_from_markdown(text),
    }
    key_map = {
        "Source X URL": "x_url",
        "Captured HTML URL": "captured_html_url",
        "Evidence URL": "evidence_url",
        "Captured Date": "date",
        "Source Type": "source_type",
        "Source Profile ID": "source_id",
        "Source Platform": "source_platform",
        "Source Account": "source_account",
        "Source User ID": "source_user_id",
        "Source Display Name": "source_display_name",
        "Thread ID": "thread_id",
        "Primary Ticker": "primary_ticker",
        "Tickers": "tickers",
        "Noise": "noise",
        "Has OCR": "has_ocr",
        "Has Media": "has_media",
        "Category": "category",
        "Signal": "signal",
        "Stance": "stance",
        "Priority": "priority",
    }
    for line in lines[:40]:
        if ": " not in line:
            continue
        raw_key, raw_value = line.split(": ", 1)
        key = key_map.get(raw_key.strip())
        if not key:
            continue
        value = raw_value.strip()
        if key in {"noise", "has_ocr", "has_media"}:
            data[key] = parse_bool(value)
        elif key == "tickers":
            data[key] = [item.strip().upper() for item in value.split(",") if item.strip()]
        else:
            data[key] = value
    data.setdefault("source_type", "x_thread")
    data.setdefault("primary_ticker", "UNKNOWN")
    data.setdefault("tickers", [])
    data.setdefault("date", "")
    data.setdefault("thread_id", "")
    data.setdefault("x_url", tweet_url(str(data["thread_id"])) if data.get("thread_id") else "")
    data.setdefault("captured_html_url", "")
    data.setdefault("evidence_url", "")
    data["media_urls"] = sorted(set(re.findall(r"Media URL: (http://[^\s]+|https://[^\s]+)", text)))
    source_post_headings = ["Source Posts", *legacy_evidence_headings("source_posts")]
    data["summary"] = extract_section(text, "Thread Summary", ["Analysis", "Evidence", *source_post_headings])
    return data


def extract_section(text: str, heading: str, next_headings: list[str]) -> str:
    start = text.find(f"## {heading}")
    if start == -1:
        return ""
    start = text.find("\n", start)
    if start == -1:
        return ""
    end = len(text)
    for next_heading in next_headings:
        idx = text.find(f"\n## {next_heading}", start)
        if idx != -1:
            end = min(end, idx)
    return clean_text(text[start:end])


def excerpt_from_markdown(text: str, limit: int = 1200) -> str:
    source_post_headings = ["Source Posts", *legacy_evidence_headings("source_posts")]
    question_headings = ["Questions Source Answered", *legacy_evidence_headings("questions_answered")]
    for heading in ("Thread Summary", "Evidence", *source_post_headings):
        section = extract_section(
            text,
            heading,
            [
                "Analysis",
                "Evidence",
                *source_post_headings,
                *question_headings,
                "Screenshots And OCR",
            ],
        )
        if section:
            return section[:limit]
    compact = clean_text(re.sub(r"```.*?```", "", text, flags=re.S))
    return compact[:limit]


def score_record(record: dict[str, Any], query: str, tickers: list[str]) -> int:
    query_terms = [term.lower() for term in re.findall(r"[A-Za-z0-9$]{2,}", query)]
    blob = " ".join(
        [
            record.get("title", ""),
            record.get("summary", ""),
            record.get("evidence_excerpt", ""),
            " ".join(record.get("tickers", [])),
            record.get("primary_ticker", ""),
            record.get("category", ""),
            record.get("signal", ""),
            record.get("stance", ""),
            record.get("evidence_markdown", "")[:5000],
        ]
    ).lower()
    score = 0
    for term in query_terms:
        score += blob.count(term)
    wanted_tickers = {ticker.upper().lstrip("$") for ticker in tickers if ticker}
    record_tickers = set(record.get("tickers", [])) | {str(record.get("primary_ticker", "")).upper()}
    if wanted_tickers and wanted_tickers.intersection(record_tickers):
        score += 25
    if record.get("primary_ticker") != "UNKNOWN":
        score += 2
    return score


class EvidenceStore:
    def __init__(self, data_dir: Path, public_base_url: str) -> None:
        self.data_dir = data_dir
        self.public_base_url = public_base_url.rstrip("/")
        self.paths = storage_paths(data_dir)
        self.x_root = self.paths.x_root
        self.evidence_dir = self.paths.legacy_x_evidence
        self.thread_json_dir = self.paths.x_records
        self.threads_dir = self.paths.x_threads_html
        self.media_dir = self.paths.x_media
        self.memory_dir = data_dir / "memory" / "tickers"

    def evidence_records(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted(self.evidence_dir.glob("*.md")):
            try:
                record = parse_frontmatterish_markdown(path)
                if record.get("evidence_url", "").startswith("http://localhost:8787"):
                    record["evidence_url"] = web_join(self.public_base_url, "evidence", path.name)
                records.append(record)
            except Exception as exc:
                print(f"WARN: Could not read evidence {path}: {exc}", file=sys.stderr)
        return records

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = clean_text(payload.get("query"))
        tickers = [str(item).upper().lstrip("$") for item in as_list(payload.get("tickers"))]
        source_types = {str(item) for item in as_list(payload.get("source_types"))}
        date_from = str(payload.get("date_from") or "")
        date_to = str(payload.get("date_to") or "")
        limit = int(payload.get("limit") or 10)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for record in self.evidence_records():
            if source_types and record.get("source_type") not in source_types:
                continue
            if date_from and str(record.get("date") or "") < date_from:
                continue
            if date_to and str(record.get("date") or "") > date_to:
                continue
            score = score_record(record, query, tickers)
            if score <= 0 and (query or tickers):
                continue
            ranked.append((score, record))
        ranked.sort(key=lambda item: (item[0], item[1].get("date", "")), reverse=True)
        results = [self.compact_result(record, score) for score, record in ranked[: max(1, min(limit, 20))]]
        return {"query": query, "results": results}

    def compact_result(self, record: dict[str, Any], score: int | None = None) -> dict[str, Any]:
        result = {
            "title": record.get("title", ""),
            "source_type": record.get("source_type", ""),
            "date": record.get("date", ""),
            "primary_ticker": record.get("primary_ticker", ""),
            "tickers": record.get("tickers", []),
            "summary": record.get("summary", ""),
            "evidence_excerpt": record.get("evidence_excerpt", ""),
            "x_url": record.get("x_url", ""),
            "captured_html_url": record.get("captured_html_url", ""),
            "evidence_url": record.get("evidence_url", ""),
            "media_urls": record.get("media_urls", []),
            "signal": record.get("signal", ""),
            "category": record.get("category", ""),
            "stance": record.get("stance", ""),
            "priority": record.get("priority", ""),
        }
        if score is not None:
            result["score"] = score
        return result

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        for record in self.evidence_records():
            if str(record.get("thread_id")) == thread_id:
                return {
                    **self.compact_result(record),
                    "thread_id": thread_id,
                    "evidence_markdown": record.get("evidence_markdown", ""),
                    "posts": self.posts_from_thread_json(thread_id),
                    "media": [{"type": "image", "url": url, "ocr_text": ""} for url in record.get("media_urls", [])],
                }
        return None

    def posts_from_thread_json(self, thread_id: str) -> list[dict[str, str]]:
        for path in self.thread_json_dir.glob(f"*__{thread_id}.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            users = data.get("users") or {}
            posts = []
            for tweet in sorted(as_list(data.get("tweets")), key=lambda item: str(item.get("created_at") or "")):
                author_id = str(tweet.get("author_id") or "")
                user = users.get(author_id) if isinstance(users, dict) else None
                username = (user or {}).get("username") or author_id or "unknown"
                tweet_id = str(tweet.get("id") or "")
                posts.append(
                    {
                        "author": f"@{username}",
                        "created_at": str(tweet.get("created_at") or ""),
                        "text": clean_text(((tweet.get("note_tweet") or {}).get("text") or tweet.get("text") or "")),
                        "x_url": tweet_url(tweet_id) if tweet_id else "",
                    }
                )
            return posts
        return []

    def ticker_memory(self, ticker: str) -> dict[str, Any]:
        ticker = ticker.upper().lstrip("$")
        path = self.memory_dir / f"{ticker}.md"
        if path.exists():
            markdown = path.read_text(encoding="utf-8")
            last_updated = ""
            match = re.search(r"Last Updated:\s*(.+)", markdown)
            if match:
                last_updated = match.group(1).strip()
        else:
            markdown = f"# {ticker} Memory\n\nNo living memory file exists yet for {ticker}.\n"
            last_updated = ""
        sources = [self.compact_result(record) for record in self.evidence_records() if ticker in set(record.get("tickers", [])) or ticker == record.get("primary_ticker")]
        sources.sort(key=lambda item: item.get("date", ""), reverse=True)
        return {"ticker": ticker, "last_updated": last_updated, "memory_markdown": markdown, "sources": sources[:20]}

    def timeline(self, payload: dict[str, Any]) -> dict[str, Any]:
        ticker = str(payload.get("ticker") or "").upper().lstrip("$")
        date_from = str(payload.get("date_from") or "")
        date_to = str(payload.get("date_to") or "")
        events = []
        for record in self.evidence_records():
            if ticker and ticker not in set(record.get("tickers", [])) and ticker != record.get("primary_ticker"):
                continue
            if date_from and str(record.get("date") or "") < date_from:
                continue
            if date_to and str(record.get("date") or "") > date_to:
                continue
            events.append(
                {
                    "date": record.get("date", ""),
                    "event_type": record.get("category", ""),
                    "summary": record.get("summary", "") or record.get("title", ""),
                    "source_url": record.get("x_url", ""),
                    "captured_html_url": record.get("captured_html_url", ""),
                    "evidence_url": record.get("evidence_url", ""),
                    "signal": record.get("signal", ""),
                    "stance": record.get("stance", ""),
                }
            )
        events.sort(key=lambda item: item.get("date", ""))
        return {"ticker": ticker, "events": events}

    def recent_signals(self, payload: dict[str, Any]) -> dict[str, Any]:
        priorities = {str(item) for item in as_list(payload.get("priority"))}
        date_from = str(payload.get("date_from") or "")
        signals = []
        for record in self.evidence_records():
            if priorities and record.get("priority") not in priorities:
                continue
            if date_from and str(record.get("date") or "") < date_from:
                continue
            if not str(record.get("signal") or "").endswith("_SIGNAL"):
                continue
            signals.append(
                {
                    "priority": record.get("priority", ""),
                    "ticker": record.get("primary_ticker", ""),
                    "summary": record.get("summary", "") or record.get("title", ""),
                    "x_url": record.get("x_url", ""),
                    "captured_html_url": record.get("captured_html_url", ""),
                    "evidence_url": record.get("evidence_url", ""),
                    "signal": record.get("signal", ""),
                    "date": record.get("date", ""),
                }
            )
        signals.sort(key=lambda item: (item.get("date", ""), item.get("priority", "")), reverse=True)
        return {"signals": signals[:50]}


def openapi_schema(base_url: str) -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Investment Evidence Tool API", "version": "0.1.0"},
        "servers": [{"url": base_url.rstrip("/")}],
        "paths": {
            "/source/search": {
                "post": {
                    "operationId": "searchEvidence",
                    "summary": "Search evidence across captured source documents.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string"},
                                        "tickers": {"type": "array", "items": {"type": "string"}},
                                        "date_from": {"type": "string"},
                                        "date_to": {"type": "string"},
                                        "source_types": {"type": "array", "items": {"type": "string"}},
                                        "limit": {"type": "integer", "default": 10},
                                    },
                                    "required": ["query"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Relevant evidence results with source links."}},
                }
            },
            "/source/thread/{thread_id}": {
                "get": {
                    "operationId": "getThread",
                    "summary": "Return one compiled thread with posts, media, and source URLs.",
                    "parameters": [{"name": "thread_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Compiled thread evidence."}},
                }
            },
            "/source/ticker/{ticker}/memory": {
                "get": {
                    "operationId": "getTickerMemory",
                    "summary": "Return living memory and recent evidence for a ticker.",
                    "parameters": [{"name": "ticker", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Ticker memory with sources."}},
                }
            },
            "/source/timeline": {
                "post": {
                    "operationId": "getTimeline",
                    "summary": "Return a ticker timeline for a date range.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "ticker": {"type": "string"},
                                        "date_from": {"type": "string"},
                                        "date_to": {"type": "string"},
                                    },
                                    "required": ["ticker"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Ticker timeline events."}},
                }
            },
            "/source/recent-signals": {
                "post": {
                    "operationId": "getRecentSignals",
                    "summary": "Return recent source action signals by priority.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "priority": {"type": "array", "items": {"type": "string"}},
                                        "date_from": {"type": "string"},
                                        "owned_only": {"type": "boolean"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Recent signal list."}},
                }
            },
        },
    }


class InvestmentToolActionHandler(BaseHTTPRequestHandler):
    store: EvidenceStore
    public_base_url: str

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_OPTIONS(self) -> None:
        self.send_json({})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        api_path = normalize_api_path(path)
        try:
            if path == "/health":
                self.send_json({"ok": True, "time": dt.datetime.now(dt.timezone.utc).isoformat()})
            elif path == "/openapi.json":
                self.send_json(openapi_schema(self.public_base_url))
            elif api_path.startswith("/thread/"):
                thread_id = api_path.removeprefix("/thread/").strip("/")
                result = self.store.get_thread(thread_id)
                if not result:
                    self.send_json({"error": "thread not found", "thread_id": thread_id}, status=404)
                else:
                    self.send_json(result)
            elif api_path.startswith("/ticker/") and api_path.endswith("/memory"):
                ticker = api_path.removeprefix("/ticker/").removesuffix("/memory").strip("/")
                self.send_json(self.store.ticker_memory(ticker))
            elif path.startswith("/threads/"):
                self.send_file(self.store.threads_dir / path.removeprefix("/threads/"))
            elif path.startswith("/media/"):
                self.send_file(self.store.media_dir / path.removeprefix("/media/"))
            elif path.startswith("/evidence/"):
                self.send_file(self.store.evidence_dir / path.removeprefix("/evidence/"))
            else:
                self.send_json({"error": "not found", "path": path}, status=404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        api_path = normalize_api_path(path)
        try:
            payload = self.read_json()
            if api_path == "/search":
                self.send_json(self.store.search(payload))
            elif api_path == "/timeline":
                self.send_json(self.store.timeline(payload))
            elif api_path == "/recent-signals":
                self.send_json(self.store.recent_signals(payload))
            else:
                self.send_json({"error": "not found", "path": path}, status=404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path) -> None:
        resolved = path.resolve()
        allowed_roots = [
            self.store.threads_dir.resolve(),
            self.store.media_dir.resolve(),
            self.store.evidence_dir.resolve(),
        ]
        if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
            self.send_json({"error": "forbidden"}, status=403)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_json({"error": "file not found"}, status=404)
            return
        content_type = "text/plain; charset=utf-8"
        if resolved.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif resolved.suffix.lower() in {".jpg", ".jpeg"}:
            content_type = "image/jpeg"
        elif resolved.suffix.lower() == ".png":
            content_type = "image/png"
        raw = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the investment evidence Action backend.")
    parser.add_argument("--source-config", default="config/sources/x_accounts.json")
    parser.add_argument("--source-id", default="")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--public-base-url", default="")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    load_env(Path(args.env_file).expanduser())
    configure_source(load_x_source_profile(args.source_config, args.source_id))
    public_base_url = (
        args.public_base_url
        or os.environ.get("INVESTMENT_TOOL_PUBLIC_BASE_URL")
        or DEFAULT_PUBLIC_BASE_URL
    )
    data_dir = resolve_portable_path(args.data_dir) if args.data_dir else storage_paths().root
    InvestmentToolActionHandler.store = EvidenceStore(data_dir, public_base_url)
    InvestmentToolActionHandler.public_base_url = public_base_url.rstrip("/")
    reporter = start_reporter(
        "action_server",
        mode="serve_forever",
        data_dir=portable_path(data_dir),
        public_base_url=public_base_url.rstrip("/"),
        x_evidence_files=len(list(storage_paths(data_dir).legacy_x_evidence.glob("*.md"))),
        article_evidence_files=len(list(storage_paths(data_dir).legacy_articles_evidence.glob("*.md"))),
        api_usage_available="request_counts_only",
    )

    server = ThreadingHTTPServer((args.host, args.port), InvestmentToolActionHandler)
    reporter.checkpoint(force=True, host=args.host, port=args.port, openapi=f"{public_base_url.rstrip('/')}/openapi.json")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
