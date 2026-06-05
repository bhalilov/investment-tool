"""Render captured X thread records into local readable HTML pages."""

from __future__ import annotations

import datetime as dt
import html
import os
from pathlib import Path
from typing import Any

from investment_tool.presentation.html import display_token, linkify_text
from investment_tool.runtime.paths import resolve_portable_path
from investment_tool.feeds.x.threads import display_text, media_keys


def tweet_url(tweet_id: str, username: str) -> str:
    return f"https://x.com/{username}/status/{tweet_id}"


def author(tweet: dict[str, Any], users: dict[str, dict]) -> str:
    user = users.get(tweet.get("author_id"), {})
    username = user.get("username") or tweet.get("author_id") or "unknown"
    return f"@{username}"


def date_prefix(tweet: dict[str, Any] | None, items: list[dict[str, Any]]) -> str:
    item = tweet or (items[0] if items else {})
    created = item.get("created_at") or ""
    return created[:10].replace("-", "") if len(created) >= 10 else dt.datetime.now().strftime("%Y%m%d")


def render_thread_html(
    path: Path,
    conversation_id: str,
    title: str,
    thread_type: str,
    label: str,
    tickers: list[str],
    tags: list[str],
    tldr: str,
    analysis_metadata: dict[str, Any],
    json_path: Path,
    items: list[dict[str, Any]],
    users: dict[str, dict],
    media: dict[str, dict],
    media_paths: dict[str, str],
    search_count: int,
    root_dir: Path,
    feed_username: str,
    feed_user_id: str,
) -> None:
    all_index_rel = os.path.relpath(root_dir / "indexes" / "index.html", path.parent)
    type_index_rel = os.path.relpath(root_dir / "indexes" / "by_type" / f"{thread_type}.html", path.parent)
    owned_json_rel = os.path.relpath(root_dir / "indexes" / "current_owned.json", path.parent)
    daily_prefix = date_prefix(items[0] if items else None, items)
    daily_name = (
        f"{daily_prefix[:4]}-{daily_prefix[4:6]}-{daily_prefix[6:8]}.html"
        if len(daily_prefix) == 8
        else f"{daily_prefix}.html"
    )
    daily_index_rel = os.path.relpath(root_dir / "indexes" / "daily" / daily_name, path.parent)
    cards: list[str] = []
    for item in sorted(items, key=lambda x: x.get("created_at") or ""):
        refs = ", ".join(f"{r.get('type')}:{r.get('id')}" for r in item.get("referenced_tweets") or []) or "none"
        metrics = item.get("public_metrics") or {}
        is_quote_context = item.get("id") != conversation_id and item.get("conversation_id") != conversation_id
        classes = "tweet quote-context" if is_quote_context else ("tweet feed" if item.get("author_id") == feed_user_id else "tweet")
        context_label = "<div class='context-label'>Quoted context</div>" if is_quote_context else ""
        note = " | full note_tweet rendered" if (item.get("note_tweet") or {}).get("text") else ""
        media_html: list[str] = []
        for key in media_keys(item):
            m = media.get(key) or {}
            local = media_paths.get(key)
            media_html.append(
                f"<div class='media-meta'>media {html.escape(key)} | {html.escape(str(m.get('type')))} "
                f"| {html.escape(str(m.get('width')))}x{html.escape(str(m.get('height')))}</div>"
            )
            if local:
                media_file = resolve_portable_path(local)
                media_src = os.path.relpath(media_file, path.parent)
                media_html.append(f"<img src='{html.escape(media_src)}' alt='downloaded X media'>")
        item_author = author(item, users)
        cards.append(
            f"""
<article class="{classes}">
  {context_label}
  <div class="head">
    <strong>{html.escape(item_author)}</strong>
    <span>{html.escape(item.get('created_at') or '')}</span>
    <a href="{tweet_url(item['id'], item_author.lstrip('@'))}" target="_blank" rel="noopener noreferrer">open on X</a>
  </div>
  <div class="meta">id {html.escape(item['id'])} | refs: {html.escape(refs)}</div>
  <div class="meta">replies: {html.escape(str(metrics.get('reply_count', 'n/a')))} |
    likes: {html.escape(str(metrics.get('like_count', 'n/a')))} |
    bookmarks: {html.escape(str(metrics.get('bookmark_count', 'n/a')))}{html.escape(note)}</div>
  <p>{linkify_text(display_text(item))}</p>
  {''.join(media_html)}
</article>
"""
        )

    primary_ticker = analysis_metadata.get("primary_ticker") or (tickers[0] if tickers else "UNKNOWN")
    primary_tickers = [] if primary_ticker == "UNKNOWN" else [primary_ticker]
    ticker_links = " ".join(
        f"<a class='pill ticker-pill' data-ticker='{html.escape(ticker)}' href='{html.escape(os.path.relpath(root_dir / 'indexes' / 'by_ticker' / f'{ticker}.html', path.parent))}'>{html.escape(ticker)}</a>"
        for ticker in primary_tickers
    ) or "<span class='pill'>none</span>"
    tag_links = " ".join(
        f"<a class='pill' href='{html.escape(os.path.relpath(root_dir / 'indexes' / 'by_tag' / f'{tag}.html', path.parent))}'>{html.escape(display_token(tag))}</a>"
        for tag in tags
    )
    context_links = " ".join(
        f"<a class='pill ticker-pill' data-ticker='{html.escape(ticker)}' href='{html.escape(os.path.relpath(root_dir / 'indexes' / 'by_ticker' / f'{ticker}.html', path.parent))}'>{html.escape(ticker)}</a>"
        for ticker in analysis_metadata.get("context_tickers") or []
    ) or "<span class='pill'>none</span>"
    mentioned_links = " ".join(
        f"<span class='pill muted ticker-pill' data-ticker='{html.escape(ticker)}'>{html.escape(ticker)}</span>"
        for ticker in analysis_metadata.get("mentioned_only_tickers") or []
    ) or "<span class='pill'>none</span>"
    flags = " ".join(
        f"<span class='pill flag'>{html.escape(display_token(flag))}</span>" for flag in analysis_metadata.get("flags") or []
    ) or "<span class='pill'>none</span>"

    def detail_list(name: str, values: list[str]) -> str:
        if not values:
            return ""
        items_html = "".join(f"<li>{html.escape(value)}</li>" for value in values)
        return f"<dt>{html.escape(name)}</dt><dd><ul>{items_html}</ul></dd>"

    json_rel = os.path.relpath(json_path, path.parent)
    root_link = tweet_url(conversation_id, feed_username)
    analysis_ready = bool(analysis_metadata.get("analysis_ready"))
    summary_label = analysis_metadata.get("summary_label") or ("TLDR" if analysis_ready else "Preview")
    analysis_stage = display_token(str(analysis_metadata.get("analysis_stage") or "captured_pending_ai_pass1"))
    if analysis_ready:
        analysis_rows = f"""
      <dt>Priority</dt><dd><span class="pill flag">{html.escape(str(analysis_metadata.get("priority") or ""))}</span></dd>
      <dt>Signal</dt><dd><span class="pill">{html.escape(display_token(str(analysis_metadata.get("signal") or "")))}</span></dd>
      <dt>Stance</dt><dd><span class="pill">{html.escape(display_token(str(analysis_metadata.get("stance") or "")))}</span></dd>
      <dt>Time horizon</dt><dd>{html.escape(display_token(str(analysis_metadata.get("time_horizon") or "")))}</dd>
      <dt>Tone</dt><dd><span class="pill">{html.escape(display_token(str(analysis_metadata.get("tone") or "")))}</span></dd>
      <dt>Score</dt><dd>actionability {html.escape(str(analysis_metadata.get("actionability_score") or 0))} / confidence {html.escape(str(analysis_metadata.get("confidence") or 0))}</dd>
      <dt>Category</dt><dd><span class="pill">{html.escape(display_token(str(analysis_metadata.get("category") or "")))}</span></dd>
      <dt>Flags</dt><dd>{flags}</dd>
      <dt>Screenshots</dt><dd>{html.escape(str(analysis_metadata.get("screenshot_importance") or ""))} / OCR needed: {html.escape(str(analysis_metadata.get("ocr_needed", False)))}</dd>
      <dt>Linked context</dt><dd>{html.escape(str(analysis_metadata.get("linked_context_required", False)))}</dd>"""
    else:
        analysis_rows = f"""
      <dt>AI status</dt><dd><span class="pill muted">{html.escape(analysis_stage)}</span></dd>"""
    displayed_summary = tldr if analysis_ready else str(analysis_metadata.get("preview_text") or "")
    path.write_text(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #17202a; }}
    h1 {{ margin-bottom: 4px; }}
    .nav {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 18px; }}
    .nav a {{ display: inline-block; padding: 6px 10px; border: 1px solid #ccd6dd; border-radius: 6px; text-decoration: none; color: #0f1419; background: #fff; }}
    .summary, .meta, .media-meta {{ color: #536471; font-size: 13px; }}
    .panel {{ border: 1px solid #d8e0e8; border-radius: 8px; padding: 14px; max-width: 980px; margin: 14px 0 20px; background: #f8fafc; }}
    .panel dl {{ display: grid; grid-template-columns: 150px 1fr; gap: 8px 12px; margin: 0; }}
    .panel dt {{ color: #536471; }}
    .panel dd {{ margin: 0; }}
    .panel ul {{ margin: 0; padding-left: 18px; }}
    .pill {{ display: inline-block; padding: 3px 8px; margin: 2px; border: 1px solid #ccd6dd; border-radius: 999px; text-decoration: none; color: #0f1419; background: #fff; font-size: 12px; }}
    .pill.owned {{ border-color: #0f766e; background: #e8f7f4; color: #075e57; font-weight: 700; }}
    .pill.flag {{ border-color: #b45309; background: #fff7ed; color: #7c2d12; }}
    .pill.muted {{ color: #536471; background: #f8fafc; }}
    .note {{ background: #fff6cc; border: 1px solid #ead36a; padding: 10px 12px; border-radius: 6px; }}
    .tweet {{ border: 1px solid #d8e0e8; border-radius: 8px; padding: 14px; margin: 14px 0; max-width: 980px; }}
    .tweet.feed {{ border-left: 5px solid #1d9bf0; }}
    .tweet.quote-context {{ border-left: 5px solid #8b5cf6; background: #fbfaff; }}
    .context-label {{ color: #6d28d9; font-size: 12px; font-weight: 700; text-transform: uppercase; margin-bottom: 6px; }}
    .head {{ display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap; }}
    p {{ white-space: pre-wrap; line-height: 1.42; }}
    img {{ display: block; max-width: 900px; max-height: 760px; margin-top: 10px; border: 1px solid #ccd6dd; }}
  </style>
</head>
<body>
  <nav class="nav">
    <a href="{html.escape(all_index_rel)}">All threads</a>
    <a href="{html.escape(type_index_rel)}">{html.escape(thread_type)} index</a>
    <a href="{html.escape(daily_index_rel)}">Daily index</a>
  </nav>
  <h1>{html.escape(title)}</h1>
  <section class="panel">
    <dl>
      <dt>{html.escape(str(summary_label))}</dt><dd>{html.escape(displayed_summary)}</dd>
      {analysis_rows}
      <dt>Primary ticker</dt><dd>{ticker_links}</dd>
      <dt>Context tickers</dt><dd>{context_links}</dd>
      <dt>Mentioned only</dt><dd>{mentioned_links}</dd>
      <dt>Tags</dt><dd>{tag_links}</dd>
      <dt>Type</dt><dd>{html.escape(thread_type)}</dd>
      <dt>Posts</dt><dd>{len(items)} captured, {sum(1 for item in items if item.get("author_id") == feed_user_id)} by feed, conversation-search results {search_count}</dd>
      <dt>Evidence</dt><dd><a href="{html.escape(json_rel)}">local JSON</a> / <a href="{html.escape(root_link)}">X root</a></dd>
      {detail_list("Evidence notes", analysis_metadata.get("evidence") or [])}
      {detail_list("Ambiguities", analysis_metadata.get("ambiguities") or [])}
      {detail_list("Contradictions", analysis_metadata.get("contradiction_flags") or [])}
    </dl>
  </section>
  <p class="note">Generated from stored X API data. HTML is a readable view; JSON and raw API responses remain the source of truth.</p>
  {''.join(cards)}
  <script>
async function applyOwnedColoring() {{
  try {{
    const response = await fetch("{html.escape(owned_json_rel)}", {{cache: "no-store"}});
    if (!response.ok) return;
    const data = await response.json();
    const owned = new Set((data.owned_tickers || []).map(t => String(t).toUpperCase()));
    document.querySelectorAll("[data-ticker]").forEach(el => {{
      if (owned.has(String(el.dataset.ticker || "").toUpperCase())) el.classList.add("owned");
    }});
  }} catch (err) {{}}
}}
applyOwnedColoring();
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
