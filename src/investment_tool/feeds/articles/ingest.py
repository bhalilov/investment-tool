#!/usr/bin/env python3
"""Ingest manually captured web-archive articles and optionally run AI analysis.

Current scope:
- Read the existing manually downloaded HTML/PDF archive.
- Extract text from saved HTML.
- Run a text-only AI pass when requested.
- Save normalized article JSON and Markdown evidence docs.

Downloader/scraper support is intentionally a placeholder for now.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Sequence

from investment_tool.analysis.openai import call_responses_json
from investment_tool.runtime.env import load_env
from investment_tool.runtime.config import read_json
from investment_tool.runtime.paths import portable_path, resolve_portable_path, storage_paths
from investment_tool.runtime.reporting import start_reporter


DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_FEED_CONFIG = "config/feeds/web_archives.json"
ARTICLE_FEED: dict[str, Any] = {}

SIGNAL_VALUES = {
    "BUY_SIGNAL",
    "SELL_SIGNAL",
    "TRIM_SIGNAL",
    "ADD_SIGNAL",
    "HOLD_SIGNAL",
    "WATCH_SIGNAL",
    "RISK_WARNING",
    "THESIS_UPDATE",
    "VALUATION_UPDATE",
    "EARNINGS_REVIEW",
    "PORTFOLIO_CONTEXT",
    "MACRO_CONTEXT",
    "NO_ACTION",
}
STANCE_VALUES = {"BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNCLEAR"}
TIME_HORIZON_VALUES = {"INTRADAY", "DAYS", "WEEKS", "MONTHS", "YEARS", "UNCLEAR"}
PRIORITY_VALUES = {"P0", "P1", "P2", "P3", "P4"}


def load_article_feed(config_path: str | Path = DEFAULT_FEED_CONFIG, feed_id: str = "") -> dict[str, Any]:
    config = read_json(config_path)
    wanted = feed_id or str(config.get("default_feed_id") or "")
    for feed in config.get("feeds") or []:
        if feed.get("feed_id") == wanted:
            return dict(feed)
    raise ValueError(f"Article feed profile not found: {wanted or '<default>'}")


def configure_article_feed(feed: dict[str, Any]) -> None:
    global ARTICLE_FEED
    ARTICLE_FEED = feed


def article_feed_name() -> str:
    return str(ARTICLE_FEED.get("display_name") or "configured web archive")


def article_feed_storage_path(name: str, fallback: Path) -> Path:
    storage = ARTICLE_FEED.get("storage") or {}
    value = storage.get(name)
    return resolve_portable_path(str(value)) if value else fallback


def article_feed_record() -> dict[str, Any]:
    return {
        "feed_id": ARTICLE_FEED.get("feed_id") or "",
        "feed_type": ARTICLE_FEED.get("feed_type") or "web_article_archive",
        "module": ARTICLE_FEED.get("module") or "articles",
        "display_name": article_feed_name(),
    }


configure_article_feed(load_article_feed())


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compact_text(value: str, limit: int = 12000) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 80].rstrip() + "\n\n[TRUNCATED FOR AI PASS]"


def safe_stem(value: str, fallback: str = "article") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:180] or fallback


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_article_date(value: str) -> str:
    text = clean_text(value)
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


class ArticleTextParser(HTMLParser):
    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
        "ol",
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.title = ""
        self._in_title = False
        self.image_alts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "img":
            attr_map = {key.lower(): value or "" for key, value in attrs}
            alt = clean_text(attr_map.get("alt"))
            if alt:
                self.image_alts.append(alt)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        self.parts.append(text + " ")

    def text(self) -> str:
        return clean_text("".join(self.parts))


def extract_html_text(path: Path) -> tuple[str, dict[str, Any]]:
    parser = ArticleTextParser()
    raw = path.read_text(encoding="utf-8", errors="replace")
    parser.feed(raw)
    text = parser.text()
    for pattern in ARTICLE_FEED.get("html_cleanup_patterns") or []:
        text = re.sub(str(pattern), "", text, flags=re.I | re.S)
    text = clean_text(text)
    return text, {
        "html_title": parser.title,
        "image_alt_texts": parser.image_alts,
        "html_sha256": sha256_text(raw),
        "text_sha256": sha256_text(text),
        "text_chars": len(text),
    }


def load_article_index(archive_dir: Path) -> list[dict[str, Any]]:
    index_path = archive_dir / "article-index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"Missing article index: {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected article-index.json to contain a list: {index_path}")
    return data


def local_archive_path(archive_dir: Path, indexed_path: str, subdir: str = "") -> Path:
    name = Path(indexed_path).name
    return archive_dir / subdir / name if subdir else archive_dir / name


def article_id(item: dict[str, Any]) -> str:
    index = int(item.get("index") or 0)
    title = clean_text(item.get("title")) or "article"
    return f"{index:03d}__{safe_stem(title.lower())}"


def article_fingerprint(item: dict[str, Any], html_meta: dict[str, Any], text: str) -> str:
    payload = {
        "index": item.get("index"),
        "title": item.get("title"),
        "url": item.get("url"),
        "date": item.get("date"),
        "html_sha256": html_meta.get("html_sha256"),
        "text_sha256": sha256_text(text),
    }
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def build_ai_prompt(item: dict[str, Any], text: str, html_meta: dict[str, Any]) -> str:
    analysis_notes = [str(note) for note in ARTICLE_FEED.get("analysis_notes") or []]
    return "\n".join(
        [
            f"Analyze this article from the configured web archive feed: {article_feed_name()}.",
            *analysis_notes,
            "Extract what would help a later AI compare X posts against older article context.",
            "Keep the output compact: summary under 90 words; arrays up to 5 short bullets; evidence up to 4 short quotes/paraphrases.",
            "Return JSON only using the schema.",
            "",
            f"Index: {item.get('index')}",
            f"Title: {item.get('title')}",
            f"Date: {item.get('date')}",
            f"Original URL: {item.get('url')}",
            f"HTML title: {html_meta.get('html_title') or ''}",
            f"Image alt text: {json.dumps(html_meta.get('image_alt_texts') or [], ensure_ascii=False)}",
            "",
            "Article text:",
            compact_text(text, 30000),
        ]
    )


def analyze_article_with_openai(
    item: dict[str, Any],
    text: str,
    html_meta: dict[str, Any],
    model: str,
) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "readable_title": {"type": "string"},
            "primary_ticker": {"type": "string"},
            "context_tickers": {"type": "array", "items": {"type": "string"}},
            "mentioned_only_tickers": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string", "maxLength": 900},
            "signal": {"type": "string", "enum": sorted(SIGNAL_VALUES)},
            "stance": {"type": "string", "enum": sorted(STANCE_VALUES)},
            "time_horizon": {"type": "string", "enum": sorted(TIME_HORIZON_VALUES)},
            "priority": {"type": "string", "enum": sorted(PRIORITY_VALUES)},
            "actionability_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "portfolio_claims": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 240}},
            "price_targets_or_ranges": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 240}},
            "thesis_points": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 240}},
            "risk_points": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 240}},
            "stale_context_flags": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 240}},
            "cross_reference_terms": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 120}},
            "evidence": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 240}},
            "ambiguities": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 240}},
        },
        "required": [
            "readable_title",
            "primary_ticker",
            "context_tickers",
            "mentioned_only_tickers",
            "summary",
            "signal",
            "stance",
            "time_horizon",
            "priority",
            "actionability_score",
            "confidence",
            "portfolio_claims",
            "price_targets_or_ranges",
            "thesis_points",
            "risk_points",
            "stale_context_flags",
            "cross_reference_terms",
            "evidence",
            "ambiguities",
        ],
    }
    try:
        analysis, _ = call_responses_json(
            api_key=api_key,
            model=model,
            system_prompt=(
                "You classify configured-feed web archive articles for a private investment archive. "
                "Use text only. Never request OCR. Output valid JSON only."
            ),
            user_content=[{"type": "input_text", "text": build_ai_prompt(item, text, html_meta)}],
            schema_name="hardcore_article_analysis",
            schema=schema,
            max_output_tokens=5000,
            timeout=90,
        )
    except Exception as exc:
        print(f"WARN: OpenAI HC analysis failed: {exc}", file=sys.stderr)
        return None
    return analysis


def markdown_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [clean_text(item) for item in values if clean_text(item)]


def render_markdown(record: dict[str, Any]) -> str:
    analysis = record.get("analysis") if isinstance(record.get("analysis"), dict) else {}
    title = clean_text(analysis.get("readable_title") or record.get("title") or "Hardcore Article")
    feed = record.get("feed") if isinstance(record.get("feed"), dict) else {}
    feed = feed if isinstance(feed, dict) else article_feed_record()
    lines = [
        f"# {title}",
        "",
        f"Feed Type: article",
        f"Feed Profile ID: {feed.get('feed_id') or ''}",
        f"Feed Display Name: {feed.get('display_name') or ''}",
        f"Article ID: {record.get('article_id')}",
        f"Article Index: {record.get('index')}",
        f"Date: {record.get('date_iso') or record.get('date')}",
        f"Ghost URL: {record.get('url')}",
        f"Captured HTML Path: {record.get('html_path')}",
        f"Captured PDF Path: {record.get('pdf_path')}",
        f"Primary Ticker: {analysis.get('primary_ticker') or 'UNKNOWN'}",
        f"Context Tickers: {', '.join(markdown_list(analysis.get('context_tickers')))}",
        f"Mentioned Only Tickers: {', '.join(markdown_list(analysis.get('mentioned_only_tickers')))}",
        f"Signal: {analysis.get('signal') or ''}",
        f"Stance: {analysis.get('stance') or ''}",
        f"Time Horizon: {analysis.get('time_horizon') or ''}",
        f"Priority: {analysis.get('priority') or ''}",
        "OCR Used: false",
    ]
    if analysis.get("summary"):
        lines.extend(["", "## AI Summary", clean_text(analysis["summary"])])
    for heading, key in (
        ("Portfolio Claims", "portfolio_claims"),
        ("Price Targets Or Ranges", "price_targets_or_ranges"),
        ("Thesis Points", "thesis_points"),
        ("Risk Points", "risk_points"),
        ("Stale Context Flags", "stale_context_flags"),
        ("Cross Reference Terms", "cross_reference_terms"),
        ("Evidence", "evidence"),
        ("Ambiguities", "ambiguities"),
    ):
        values = markdown_list(analysis.get(key))
        if values:
            lines.extend(["", f"## {heading}"])
            lines.extend(f"- {item}" for item in values)
    lines.extend(["", "## Extracted Article Text", clean_text(record.get("text"))])
    return "\n".join(lines).strip() + "\n"


def download_placeholder(_: argparse.Namespace) -> None:
    raise NotImplementedError(
        "Hardcore/Ghost downloading is intentionally manual for now. "
        "Add browser/scraper support here later."
    )


def process_articles(args: argparse.Namespace) -> int:
    storage = storage_paths()
    archive_dir = resolve_portable_path(args.archive_dir) if args.archive_dir else storage.articles_archive
    output_dir = resolve_portable_path(args.output_dir) if args.output_dir else storage.articles_root
    article_json_dir = resolve_portable_path(args.records_dir) if args.records_dir else storage.articles_records
    evidence_dir = resolve_portable_path(args.evidence_dir) if args.evidence_dir else storage.legacy_articles_evidence
    manifest_path = resolve_portable_path(args.manifest) if args.manifest else storage.articles_manifest
    index = load_article_index(archive_dir)
    if args.limit:
        index = index[: args.limit]
    model = args.model or os.environ.get("OPENAI_HARDCORE_MODEL") or os.environ.get("OPENAI_ANALYSIS_MODEL") or DEFAULT_OPENAI_MODEL
    existing_complete = 0
    if article_json_dir.exists() and not args.force_ai:
        for item in index:
            aid = article_id(item)
            html_path = local_archive_path(archive_dir, str(item.get("htmlPath") or ""), "_html")
            out_json = article_json_dir / f"{aid}.json"
            if not html_path.exists() or not out_json.exists():
                continue
            try:
                text, html_meta = extract_html_text(html_path)
                fingerprint = article_fingerprint(item, html_meta, text)
                existing = json.loads(out_json.read_text(encoding="utf-8"))
                if existing.get("fingerprint") == fingerprint and existing.get("analysis"):
                    existing_complete += 1
            except Exception:
                pass
    reporter = start_reporter(
        "articles",
        total=len(index),
        every_items=5,
        every_seconds=30,
        mode="dry_run" if args.dry_run else "write",
        analyze=str(not args.no_analyze).lower(),
        force_ai=str(args.force_ai).lower(),
        model=model,
        archive_dir=portable_path(archive_dir),
        output_dir=portable_path(output_dir),
        records_dir=portable_path(article_json_dir),
        evidence_dir=portable_path(evidence_dir),
        found_articles=len(index),
        already_analyzed=existing_complete,
        pending_ai=max(0, len(index) - existing_complete) if not args.no_analyze else 0,
        ocr="false",
        openai_usage_available="tokens_from_responses",
    )
    if not args.dry_run:
        article_json_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "seen": 0,
        "written_json": 0,
        "written_evidence": 0,
        "ai_analyzed": 0,
        "ai_skipped": 0,
        "missing_html": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    for item in index:
        stats["seen"] += 1
        aid = article_id(item)
        html_path = local_archive_path(archive_dir, str(item.get("htmlPath") or ""), "_html")
        pdf_path = local_archive_path(archive_dir, str(item.get("pdfPath") or ""))
        if not html_path.exists():
            stats["missing_html"] += 1
            print(f"WARN: Missing HTML for {aid}: {html_path}", file=sys.stderr)
            continue
        text, html_meta = extract_html_text(html_path)
        fingerprint = article_fingerprint(item, html_meta, text)
        out_json = article_json_dir / f"{aid}.json"
        existing: dict[str, Any] = {}
        if out_json.exists():
            try:
                existing = json.loads(out_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        analysis = existing.get("analysis") if existing.get("fingerprint") == fingerprint and not args.force_ai else None
        if args.no_analyze:
            stats["ai_skipped"] += 1
        elif analysis:
            stats["ai_skipped"] += 1
        else:
            analysis = analyze_article_with_openai(item, text, html_meta, model)
            if analysis:
                analysis["analyzed_at"] = iso_now()
                analysis["input_fingerprint"] = fingerprint
                stats["ai_analyzed"] += 1
                stats["input_tokens"] += int(analysis.get("_input_tokens") or 0)
                stats["output_tokens"] += int(analysis.get("_output_tokens") or 0)
            else:
                stats["ai_skipped"] += 1
        record = {
            "article_id": aid,
            "index": item.get("index"),
            "title": clean_text(item.get("title")),
            "url": item.get("url"),
            "date": item.get("date"),
            "date_iso": parse_article_date(str(item.get("date") or "")),
            "html_path": portable_path(html_path),
            "pdf_path": portable_path(pdf_path) if pdf_path.exists() else "",
            "text": text,
            "html_meta": html_meta,
            "analysis": analysis,
            "fingerprint": fingerprint,
            "feed": article_feed_record(),
            "captured_by": "manual_archive",
            "updated_at": iso_now(),
            "ocr_used": False,
        }
        markdown = render_markdown(record)
        out_md = evidence_dir / f"{aid}.md"
        if args.dry_run:
            print(f"Would write {out_json}")
            print(f"Would write {out_md}")
        else:
            previous_json = out_json.read_text(encoding="utf-8") if out_json.exists() else None
            next_json = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
            if previous_json != next_json:
                out_json.write_text(next_json, encoding="utf-8")
                stats["written_json"] += 1
            previous_md = out_md.read_text(encoding="utf-8") if out_md.exists() else None
            if previous_md != markdown:
                out_md.write_text(markdown, encoding="utf-8")
                stats["written_evidence"] += 1
        reporter.checkpoint_stats(
            stats,
            processed=stats["seen"],
            token_model=model,
        )

    manifest = {
        "generated_at": iso_now(),
        "archive_dir": portable_path(archive_dir),
        "output_dir": portable_path(output_dir),
        "records_dir": portable_path(article_json_dir),
        "evidence_dir": portable_path(evidence_dir),
        "model": model,
        **stats,
    }
    if not args.dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    reporter.done_stats(
        stats,
        token_model=model,
        manifest=portable_path(manifest_path),
    )
    return 0 if stats["missing_html"] == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest manually captured web-archive articles.")
    parser.add_argument("--feed-config", default=DEFAULT_FEED_CONFIG)
    parser.add_argument("--feed-id", default="")
    parser.add_argument("--archive-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--records-dir", default="")
    parser.add_argument("--evidence-dir", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--model", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-analyze", action="store_true", help="Only normalize HTML into JSON/Markdown; do not call OpenAI.")
    parser.add_argument("--force-ai", action="store_true", help="Re-run AI even when article fingerprint is unchanged.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--download", action="store_true", help="Placeholder only; downloading remains manual for now.")
    args = parser.parse_args(argv)

    load_env(Path(args.env))
    configure_article_feed(load_article_feed(args.feed_config, args.feed_id))
    storage = storage_paths()
    if not args.archive_dir:
        args.archive_dir = str(article_feed_storage_path("archive_dir", storage.articles_archive))
    if not args.records_dir:
        args.records_dir = str(article_feed_storage_path("records_dir", storage.articles_records))
    if not args.evidence_dir:
        args.evidence_dir = str(article_feed_storage_path("evidence_dir", storage.legacy_articles_evidence))
    if not args.manifest:
        args.manifest = str(article_feed_storage_path("manifest_path", storage.articles_manifest))
    if not args.output_dir:
        args.output_dir = str(article_feed_storage_path("output_dir", storage.articles_root))
    if args.download:
        download_placeholder(args)
    return process_articles(args)


if __name__ == "__main__":
    raise SystemExit(main())
