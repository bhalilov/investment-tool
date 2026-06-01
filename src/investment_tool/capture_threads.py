"""Capture AJ X threads, media, raw API responses, JSON snapshots, and HTML reports."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


API_BASE = "https://api.x.com/2"
AJ_USERNAME = "alojohhardcore"
AJ_USER_ID = "2033476611149066240"

TWEET_FIELDS = ",".join(
    [
        "id",
        "text",
        "note_tweet",
        "article",
        "created_at",
        "author_id",
        "conversation_id",
        "referenced_tweets",
        "attachments",
        "public_metrics",
        "entities",
        "edit_history_tweet_ids",
        "edit_controls",
        "lang",
        "possibly_sensitive",
        "in_reply_to_user_id",
    ]
)
EXPANSIONS = ",".join(
    [
        "attachments.media_keys",
        "referenced_tweets.id",
        "referenced_tweets.id.author_id",
        "author_id",
        "in_reply_to_user_id",
        "entities.mentions.username",
    ]
)
MEDIA_FIELDS = "media_key,type,url,preview_image_url,width,height,alt_text,variants"
USER_FIELDS = "id,username,name,verified,verified_type,protected"

STOPWORDS = {
    "about",
    "after",
    "again",
    "already",
    "answer",
    "because",
    "before",
    "being",
    "channel",
    "continue",
    "could",
    "current",
    "every",
    "first",
    "from",
    "have",
    "here",
    "receive",
    "into",
    "just",
    "late",
    "like",
    "more",
    "much",
    "question",
    "questions",
    "same",
    "should",
    "still",
    "that",
    "their",
    "there",
    "this",
    "through",
    "when",
    "where",
    "will",
    "with",
    "would",
}
COMPANY_TICKERS = {
    "micron": "MU",
    "palantir": "PLTR",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "meta": "META",
    "microsoft": "MSFT",
    "apple": "AAPL",
    "alphabet": "GOOG",
    "google": "GOOG",
    "rivian": "RIVN",
    "xpeng": "XPEV",
    "intel": "INTC",
    "broadcom": "AVGO",
    "amd": "AMD",
    "uber": "UBER",
    "lite": "LITE",
    "lumentum": "LITE",
}
KNOWN_TICKERS = set(COMPANY_TICKERS.values()) | {"QQQ", "SPY", "TSM"}
TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")
X_STATUS_RE = re.compile(r"https?://(?:mobile\.)?(?:x|twitter)\.com/[^/\s]+/status/(\d+)")
DEFAULT_X_POST_READ_COST_USD = 0.005


def load_cached_threads(
    json_dir: Path,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
) -> dict[str, set[str]]:
    """Load all previously captured thread JSONs into the in-memory dicts.

    Returns a mapping of conversation_id -> set of tweet IDs that were in the
    cache, so the caller can detect whether new replies have arrived since the
    last capture.
    """
    cached: dict[str, set[str]] = {}
    for json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        conv_id = data.get("conversation_id")
        if not conv_id:
            continue
        tweet_ids: set[str] = set()
        for tweet in data.get("tweets") or []:
            tweets[tweet["id"]] = tweet
            tweet_ids.add(tweet["id"])
        users.update(data.get("users") or {})
        media.update(data.get("media") or {})
        cached[conv_id] = tweet_ids
    return cached


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def data_root() -> Path:
    return Path(os.environ.get("INVESTMENT_TOOL_DATA_DIR", "~/investment-tool-data")).expanduser()


def tweet_params(**extra: str | int) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "tweet.fields": TWEET_FIELDS,
        "expansions": EXPANSIONS,
        "media.fields": MEDIA_FIELDS,
        "user.fields": USER_FIELDS,
    }
    params.update(extra)
    return params


def safe_slug(value: str, fallback: str = "thread") -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:90] or fallback


def display_text(tweet: dict) -> str:
    note_text = ((tweet.get("note_tweet") or {}).get("text") or "").strip()
    if note_text:
        return note_text
    return tweet.get("text") or ""


def tweet_url(tweet_id: str, username: str = AJ_USERNAME) -> str:
    return f"https://x.com/{username}/status/{tweet_id}"


def media_keys(tweet: dict) -> list[str]:
    return (tweet.get("attachments") or {}).get("media_keys") or []


class XClient:
    def __init__(self, token: str, raw_dir: Path) -> None:
        self.token = token
        self.raw_dir = raw_dir
        self.call_count = 0
        self.rate_limits: list[dict[str, str | None]] = []
        self.post_ids_returned: set[str] = set()

    def get(self, path: str, params: dict[str, str | int] | None = None, label: str = "api") -> dict:
        params = params or {}
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        self.call_count += 1
        fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                headers = dict(resp.headers)
                status = resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw_error": body}
            headers = dict(exc.headers)
            status = exc.code

        rate = {
            "label": label,
            "status": str(status),
            "limit": headers.get("x-rate-limit-limit"),
            "remaining": headers.get("x-rate-limit-remaining"),
            "reset": headers.get("x-rate-limit-reset"),
        }
        self.rate_limits.append(rate)
        self.post_ids_returned.update(extract_response_post_ids(data))
        raw_path = self.raw_dir / f"{self.call_count:04d}_{safe_slug(label, 'api')}_{status}.json"
        raw_path.write_text(
            json.dumps(
                {
                    "fetched_at": fetched_at,
                    "url": url,
                    "status": status,
                    "rate_limit": rate,
                    "response": data,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if status >= 400:
            raise RuntimeError(f"X API error {status} for {label}: {json.dumps(data)[:500]}")
        return data


def extract_response_post_ids(response: dict) -> set[str]:
    ids: set[str] = set()
    for tweet in response.get("data") or []:
        if tweet.get("id"):
            ids.add(tweet["id"])
    for tweet in (response.get("includes") or {}).get("tweets") or []:
        if tweet.get("id"):
            ids.add(tweet["id"])
    return ids


def merge_response(response: dict, tweets: dict[str, dict], users: dict[str, dict], media: dict[str, dict]) -> None:
    for tweet in response.get("data") or []:
        tweets[tweet["id"]] = tweet
    includes = response.get("includes") or {}
    for tweet in includes.get("tweets") or []:
        tweets[tweet["id"]] = tweet
    for user in includes.get("users") or []:
        users[user["id"]] = user
    for item in includes.get("media") or []:
        media[item["media_key"]] = item


def fetch_tweets_by_ids(
    client: XClient,
    ids: list[str],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    label: str,
) -> None:
    missing = [tweet_id for tweet_id in ids if tweet_id and tweet_id not in tweets]
    for i in range(0, len(missing), 100):
        chunk = missing[i : i + 100]
        if not chunk:
            continue
        response = client.get("/tweets", tweet_params(ids=",".join(chunk)), f"{label}_{i // 100 + 1}")
        merge_response(response, tweets, users, media)


def fetch_timeline(
    client: XClient,
    pages: int,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
) -> list[str]:
    seed_ids: list[str] = []
    pagination_token: str | None = None
    for page in range(pages):
        params = tweet_params(max_results=100)
        if pagination_token:
            params["pagination_token"] = pagination_token
        response = client.get(f"/users/{AJ_USER_ID}/tweets", params, f"aj_timeline_page_{page + 1}")
        merge_response(response, tweets, users, media)
        for item in response.get("data") or []:
            seed_ids.append(item["id"])
        pagination_token = (response.get("meta") or {}).get("next_token")
        if not pagination_token:
            break
    return seed_ids


def referenced_ids(tweet: dict) -> list[str]:
    return [ref["id"] for ref in tweet.get("referenced_tweets") or [] if ref.get("id")]


def parent_id(tweet: dict) -> str | None:
    return next((ref.get("id") for ref in tweet.get("referenced_tweets") or [] if ref.get("type") == "replied_to"), None)


def explicit_x_links(tweet: dict) -> list[str]:
    ids: list[str] = []
    blobs = [tweet.get("entities") or {}, (tweet.get("note_tweet") or {}).get("entities") or {}]
    for blob in blobs:
        for url_obj in blob.get("urls") or []:
            for key in ("expanded_url", "url"):
                value = url_obj.get(key) or ""
                match = X_STATUS_RE.search(value)
                if match:
                    ids.append(match.group(1))
    for match in X_STATUS_RE.finditer(display_text(tweet)):
        ids.append(match.group(1))
    return list(dict.fromkeys(ids))


def walk_context(
    client: XClient,
    seed_ids: list[str],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    depth_limit: int = 20,
) -> None:
    queue = list(dict.fromkeys(seed_ids))
    seen: set[str] = set()
    while queue:
        tweet_id = queue.pop(0)
        if tweet_id in seen:
            continue
        seen.add(tweet_id)
        if tweet_id not in tweets:
            fetch_tweets_by_ids(client, [tweet_id], tweets, users, media, "context_lookup")
        tweet = tweets.get(tweet_id)
        if not tweet:
            continue
        for ref_id in referenced_ids(tweet):
            if ref_id not in seen:
                queue.append(ref_id)
        for linked_id in explicit_x_links(tweet):
            if linked_id not in seen:
                queue.append(linked_id)

        current = tweet
        for _ in range(depth_limit):
            pid = parent_id(current)
            if not pid or pid in seen:
                break
            if pid not in tweets:
                fetch_tweets_by_ids(client, [pid], tweets, users, media, "parent_chain")
            parent = tweets.get(pid)
            if not parent:
                break
            queue.append(pid)
            current = parent


def search_conversation(
    client: XClient,
    conversation_id: str,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    pages: int,
) -> int:
    count = 0
    next_token: str | None = None
    for page in range(pages):
        params = tweet_params(query=f"conversation_id:{conversation_id}", max_results=100)
        if next_token:
            params["next_token"] = next_token
        response = client.get("/tweets/search/recent", params, f"conversation_{conversation_id}_page_{page + 1}")
        count += len(response.get("data") or [])
        merge_response(response, tweets, users, media)
        next_token = (response.get("meta") or {}).get("next_token")
        if not next_token:
            break
        time.sleep(0.2)
    return count


def download_photos(media: dict[str, dict], media_dir: Path, wanted_keys: set[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for key, item in media.items():
        if key not in wanted_keys:
            continue
        if item.get("type") != "photo" or not item.get("url"):
            continue
        url = item["url"]
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
        path = media_dir / f"{key}{suffix}"
        if not path.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "investment-tool/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                path.write_bytes(resp.read())
        paths[key] = str(path)
    return paths


def extract_tickers(text: str) -> list[str]:
    explicit = [ticker for ticker in TICKER_RE.findall(text) if ticker in KNOWN_TICKERS]
    lower = text.lower()
    inferred = [ticker for name, ticker in COMPANY_TICKERS.items() if name in lower]
    return list(dict.fromkeys(inferred + explicit))


def thread_title(root: dict | None, items: list[dict]) -> tuple[str, str]:
    source = root or (items[0] if items else {})
    text = display_text(source)
    aj_items = [item for item in items if item.get("author_id") == AJ_USER_ID]
    tickers = extract_tickers(" ".join([text] + [display_text(item) for item in aj_items]))
    topic = topic_phrase(text)
    prefix = "/".join(tickers[:3]) if tickers else "X"
    title = f"{prefix} - {topic}"
    return title, safe_slug(topic)


def topic_phrase(text: str) -> str:
    cleaned = html.unescape(re.sub(r"https?://\S+", "", text)).strip()
    first_para = cleaned.split("\n\n", 1)[0].strip()
    if ":" in first_para:
        before, after = first_para.split(":", 1)
        company = next((name.title() for name in COMPANY_TICKERS if re.search(rf"\b{name}\b", before, re.I)), "")
        after = after.strip(" -")
        if company and after:
            return f"{company}: {after[:90]}".strip()
    match = re.search(r"(.{20,180}?[?.!])(?:\s|$)", first_para)
    phrase = (match.group(1) if match else first_para[:120]).strip()
    words = phrase.split()
    return " ".join(words[:14]) if words else "X thread"


def date_prefix(tweet: dict | None, items: list[dict]) -> str:
    source = tweet or (items[0] if items else {})
    created = source.get("created_at") or ""
    return created[:10].replace("-", "") if len(created) >= 10 else dt.datetime.now().strftime("%Y%m%d")


def primary_label(tickers: list[str], tags: list[str]) -> str:
    if tickers:
        return "-".join(tickers[:3])
    for label in ("MARKET", "SPACEX", "RANT", "BRAG", "NOISE"):
        if label in tags:
            return label
    return "UNKNOWN"


def infer_tags(items: list[dict], thread_type: str, tickers: list[str]) -> list[str]:
    aj_items = [item for item in items if item.get("author_id") == AJ_USER_ID]
    source_items = aj_items or items
    text = "\n".join(display_text(item) for item in source_items).lower()
    tags = [thread_type]
    if any(media_keys(item) for item in items):
        tags.append("SCREENSHOT")
    if any((item.get("note_tweet") or {}).get("text") for item in items):
        tags.append("NOTE_TWEET")
    if any(explicit_x_links(item) for item in items):
        tags.append("X_LINKED_CONTEXT")
    if "ghost.io" in text or "aj-investment-research.ghost.io" in text:
        tags.append("GHOST_LINKED")
    if re.search(r"\b(bought|sold|trimmed|exited|added|shorted|covered|closed|reloaded)\b", text):
        tags.append("LIVE_TRADE")
    if re.search(r"\b(buy|sell|avoid|wait|do not chase|risk/reward|too late)\b", text):
        tags.append("ADVICE_WARNING")
    if any(word in text for word in ("valuation", "thesis", "earnings", "multiple", "corridor", "macro", "forecast")):
        tags.append("THESIS_UPDATE")
    if "spacex" in text or "starlink" in text:
        tags.append("SPACEX")
    if not tickers and any(word in text for word in ("s&p", "sp500", "market", "qqq", "spy", "macro")):
        tags.append("MARKET")
    if any(phrase in text for phrase in ("we nailed", "called it", "we called", "nailed it")):
        tags.append("BRAG")
    if any(word in text for word in ("politics", "rant", "nonsense")):
        tags.append("RANT")
    return list(dict.fromkeys(tags))


def rough_tldr(items: list[dict]) -> str:
    ordered = sorted(items, key=lambda x: x.get("created_at") or "")
    aj_items = [item for item in ordered if item.get("author_id") == AJ_USER_ID]
    source = aj_items[0] if aj_items else (ordered[0] if ordered else {})
    words = display_text(source).strip().replace("\n", " ").split()
    return " ".join(words[:55]) + ("..." if len(words) > 55 else "")


def author(tweet: dict, users: dict[str, dict]) -> str:
    user = users.get(tweet.get("author_id"), {})
    username = user.get("username") or tweet.get("author_id") or "unknown"
    return f"@{username}"


def classify_thread(root: dict | None, items: list[dict]) -> str:
    if root and root.get("author_id") == AJ_USER_ID:
        return "AJ_THREAD"
    if any(item.get("author_id") == AJ_USER_ID for item in items):
        return "AJ_REPLY_CONTEXT"
    return "LINKED_CONTEXT"


def render_thread_html(
    path: Path,
    conversation_id: str,
    title: str,
    thread_type: str,
    label: str,
    tickers: list[str],
    tags: list[str],
    tldr: str,
    json_path: Path,
    items: list[dict],
    users: dict[str, dict],
    media: dict[str, dict],
    media_paths: dict[str, str],
    search_count: int,
    root_dir: Path,
) -> None:
    cards: list[str] = []
    for item in sorted(items, key=lambda x: x.get("created_at") or ""):
        refs = ", ".join(f"{r.get('type')}:{r.get('id')}" for r in item.get("referenced_tweets") or []) or "none"
        metrics = item.get("public_metrics") or {}
        classes = "tweet aj" if item.get("author_id") == AJ_USER_ID else "tweet"
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
                media_html.append(f"<img src='{Path(local).as_uri()}' alt='downloaded X media'>")
        cards.append(
            f"""
<article class="{classes}">
  <div class="head">
    <strong>{html.escape(author(item, users))}</strong>
    <span>{html.escape(item.get('created_at') or '')}</span>
    <a href="{tweet_url(item['id'], author(item, users).lstrip('@'))}">open on X</a>
  </div>
  <div class="meta">id {html.escape(item['id'])} | refs: {html.escape(refs)}</div>
  <div class="meta">replies: {html.escape(str(metrics.get('reply_count', 'n/a')))} |
    likes: {html.escape(str(metrics.get('like_count', 'n/a')))} |
    bookmarks: {html.escape(str(metrics.get('bookmark_count', 'n/a')))}{html.escape(note)}</div>
  <p>{html.escape(display_text(item))}</p>
  {''.join(media_html)}
</article>
"""
        )

    ticker_links = " ".join(
        f"<a class='pill' href='{html.escape(os.path.relpath(root_dir / 'indexes' / 'by_ticker' / f'{ticker}.html', path.parent))}'>{html.escape(ticker)}</a>"
        for ticker in tickers
    ) or "<span class='pill'>none</span>"
    tag_links = " ".join(
        f"<a class='pill' href='{html.escape(os.path.relpath(root_dir / 'indexes' / 'by_tag' / f'{tag}.html', path.parent))}'>{html.escape(tag)}</a>"
        for tag in tags
    )
    json_rel = os.path.relpath(json_path, path.parent)
    root_link = tweet_url(conversation_id, AJ_USERNAME)
    path.write_text(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #17202a; }}
    h1 {{ margin-bottom: 4px; }}
    .summary, .meta, .media-meta {{ color: #536471; font-size: 13px; }}
    .panel {{ border: 1px solid #d8e0e8; border-radius: 8px; padding: 14px; max-width: 980px; margin: 14px 0 20px; background: #f8fafc; }}
    .panel dl {{ display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; margin: 0; }}
    .panel dt {{ color: #536471; }}
    .panel dd {{ margin: 0; }}
    .pill {{ display: inline-block; padding: 3px 8px; margin: 2px; border: 1px solid #ccd6dd; border-radius: 999px; text-decoration: none; color: #0f1419; background: #fff; font-size: 12px; }}
    .note {{ background: #fff6cc; border: 1px solid #ead36a; padding: 10px 12px; border-radius: 6px; }}
    .tweet {{ border: 1px solid #d8e0e8; border-radius: 8px; padding: 14px; margin: 14px 0; max-width: 980px; }}
    .tweet.aj {{ border-left: 5px solid #1d9bf0; }}
    .head {{ display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap; }}
    p {{ white-space: pre-wrap; line-height: 1.42; }}
    img {{ display: block; max-width: 900px; max-height: 760px; margin-top: 10px; border: 1px solid #ccd6dd; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <section class="panel">
    <dl>
      <dt>TLDR</dt><dd>{html.escape(tldr)}</dd>
      <dt>Label</dt><dd><span class="pill">{html.escape(label)}</span></dd>
      <dt>Tickers</dt><dd>{ticker_links}</dd>
      <dt>Tags</dt><dd>{tag_links}</dd>
      <dt>Type</dt><dd>{html.escape(thread_type)}</dd>
      <dt>Posts</dt><dd>{len(items)} captured, {sum(1 for item in items if item.get("author_id") == AJ_USER_ID)} by AJ, conversation-search results {search_count}</dd>
      <dt>Evidence</dt><dd><a href="{html.escape(json_rel)}">local JSON</a> · <a href="{html.escape(root_link)}">X root</a></dd>
    </dl>
  </section>
  <p class="note">Generated from stored X API data. HTML is a readable view; JSON and raw API responses remain the source of truth.</p>
  {''.join(cards)}
</body>
</html>
""",
        encoding="utf-8",
    )


def render_index(path: Path, entries: list[dict], title: str = "AJ Thread Capture Index") -> None:
    rows = "\n".join(
        f"<tr>"
        f"<td><span class='rel-time' data-ts='{html.escape(e['date'])}' title='{html.escape(e['date'])}'>{html.escape(e['date'])}</span></td>"
        f"<td>{html.escape(e['label'])}</td>"
        f"<td><a href='{html.escape(os.path.relpath(e['abs_path'], path.parent))}'>{html.escape(e['title'])}</a></td>"
        f"<td>{html.escape(e['type'])}</td><td>{html.escape(', '.join(e['tickers']) or 'none')}</td>"
        f"<td>{html.escape(', '.join(e['tags']))}</td><td>{e['posts']}</td><td>{e['aj_posts']}</td><td>{e['photos']}</td>"
        f"</tr>"
        for e in entries
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:24px;color:#17202a}}
table{{border-collapse:collapse}}td,th{{border:1px solid #d8e0e8;padding:7px 9px;text-align:left}}
.rel-time{{white-space:nowrap;color:#536471;font-size:13px}}
</style></head>
<body><h1>{html.escape(title)}</h1><table>
<tr><th>Captured</th><th>Label</th><th>Thread</th><th>Type</th><th>Tickers</th><th>Tags</th><th>Posts</th><th>AJ Posts</th><th>Photos</th></tr>
{rows}</table>
<script>
function relTime(iso) {{
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + ' min ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  if (diff < 86400*2) return 'yesterday';
  if (diff < 86400*7) return Math.floor(diff/86400) + ' days ago';
  if (diff < 86400*30) return Math.floor(diff/86400/7) + ' weeks ago';
  return new Date(iso).toLocaleDateString();
}}
document.querySelectorAll('.rel-time').forEach(el => {{
  const ts = el.dataset.ts;
  if (ts) el.textContent = relTime(ts);
}});
</script>
</body></html>""",
        encoding="utf-8",
    )


def render_all_indexes(root: Path, entries: list[dict]) -> None:
    indexes = root / "indexes"
    sorted_entries = sorted(entries, key=lambda e: (e["date"], e["label"], e["title"]), reverse=True)
    render_index(indexes / "index.html", sorted_entries, "All Captured Threads")
    for ticker in sorted({ticker for entry in entries for ticker in entry["tickers"]}):
        render_index(indexes / "by_ticker" / f"{ticker}.html", [e for e in sorted_entries if ticker in e["tickers"]], f"Threads for {ticker}")
    for thread_type in sorted({entry["type"] for entry in entries}):
        render_index(indexes / "by_type" / f"{thread_type}.html", [e for e in sorted_entries if e["type"] == thread_type], f"{thread_type} Threads")
    for tag in sorted({tag for entry in entries for tag in entry["tags"]}):
        render_index(indexes / "by_tag" / f"{tag}.html", [e for e in sorted_entries if tag in e["tags"]], f"Threads tagged {tag}")
    for date in sorted({entry["date"] for entry in entries}, reverse=True):
        render_index(indexes / "daily" / f"{date}.html", [e for e in sorted_entries if e["date"] == date], f"Threads captured for {date}")


def write_usage_estimate(root: Path, run_id: str, client: XClient) -> dict:
    usage_dir = root / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    cost_per_post = float(os.environ.get("X_POST_READ_COST_USD", DEFAULT_X_POST_READ_COST_USD))
    credit_start = float(os.environ.get("X_CREDIT_START_USD", "25"))
    unique_reads = len(client.post_ids_returned)
    estimated_cost = unique_reads * cost_per_post
    record = {
        "run_id": run_id,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "api_calls": client.call_count,
        "unique_post_ids_returned": unique_reads,
        "estimated_cost_usd": round(estimated_cost, 4),
        "cost_per_post_read_usd": cost_per_post,
        "credit_start_usd": credit_start,
        "estimated_remaining_if_starting_credit_applies_usd": round(max(0.0, credit_start - estimated_cost), 4),
        "note": "Rough estimate only. X billing uses daily deduplication and endpoint-specific pricing.",
    }
    with (usage_dir / "usage_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (usage_dir / "latest_usage_estimate.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture AJ X threads into readable local HTML files.")
    parser.add_argument("--timeline-pages", type=int, default=3)
    parser.add_argument("--conversation-pages", type=int, default=5)
    parser.add_argument("--max-threads", type=int, default=20)
    parser.add_argument("--conversation-id")
    parser.add_argument("--force", action="store_true", help="Re-fetch and overwrite already-cached threads")
    args = parser.parse_args()

    load_env(Path.cwd() / ".env")
    token = os.environ.get("X_USER_ACCESS_TOKEN", "").strip()
    if not token:
        print("Missing X_USER_ACCESS_TOKEN in .env", file=sys.stderr)
        return 1

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = data_root() / "x_threads"
    raw_dir = root / "raw_api" / run_id
    json_dir = root / "thread_json"
    media_dir = root / "media"
    threads_dir = root / "threads"
    for folder in (raw_dir, json_dir, media_dir, threads_dir, root / "indexes"):
        folder.mkdir(parents=True, exist_ok=True)

    client = XClient(token, raw_dir)
    tweets: dict[str, dict] = {}
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}

    cached_tweet_ids = load_cached_threads(json_dir, tweets, users, media)
    cached_conversation_ids = set(cached_tweet_ids.keys())
    if cached_conversation_ids:
        print(f"CACHED={len(cached_conversation_ids)} threads found locally")

    seed_ids = fetch_timeline(client, args.timeline_pages, tweets, users, media)
    if args.conversation_id:
        seed_ids.append(args.conversation_id)
        fetch_tweets_by_ids(client, [args.conversation_id], tweets, users, media, "requested_conversation")
    walk_context(client, seed_ids, tweets, users, media)

    conversation_ids: list[str] = []
    if args.conversation_id:
        conversation_ids = [args.conversation_id]
    else:
        for tweet in sorted(tweets.values(), key=lambda item: item.get("created_at") or "", reverse=True):
            if tweet.get("author_id") != AJ_USER_ID:
                continue
            conv = tweet.get("conversation_id")
            if conv and conv not in conversation_ids:
                conversation_ids.append(conv)
            if len(conversation_ids) >= args.max_threads:
                break

    # A cached thread has new replies if the timeline fetch introduced tweet IDs
    # that weren't in the stored JSON. Those threads need a full conversation
    # search so we pick up any replies we haven't seen yet.
    def has_new_tweets(conv_id: str) -> bool:
        known = cached_tweet_ids.get(conv_id, set())
        current = {tid for tid, t in tweets.items() if t.get("conversation_id") == conv_id}
        return bool(current - known)

    search_counts: dict[str, int] = {}
    for conversation_id in conversation_ids:
        if not args.force and conversation_id in cached_conversation_ids and not has_new_tweets(conversation_id):
            search_counts[conversation_id] = 0
            continue
        search_counts[conversation_id] = search_conversation(
            client, conversation_id, tweets, users, media, args.conversation_pages
        )
        conv_ids = [tweet_id for tweet_id, tweet in tweets.items() if tweet.get("conversation_id") == conversation_id]
        walk_context(client, conv_ids, tweets, users, media)

    by_conversation: dict[str, list[dict]] = defaultdict(list)
    for tweet in tweets.values():
        conv = tweet.get("conversation_id")
        if conv in conversation_ids:
            by_conversation[conv].append(tweet)

    entries: list[dict] = []
    wanted_media_keys = {key for items in by_conversation.values() for item in items for key in media_keys(item)}
    media_paths = download_photos(media, media_dir, wanted_media_keys)
    for conversation_id, items in by_conversation.items():
        root_tweet = tweets.get(conversation_id)
        title, slug = thread_title(root_tweet, items)
        aj_items = [item for item in items if item.get("author_id") == AJ_USER_ID]
        ticker_text = " ".join([display_text(root_tweet or {})] + [display_text(item) for item in aj_items])
        tickers = extract_tickers(ticker_text)
        thread_type = classify_thread(root_tweet, items)
        tags = infer_tags(items, thread_type, tickers)
        label = primary_label(tickers, tags)
        tldr = rough_tldr(items)
        prefix = date_prefix(root_tweet, items)
        filename = f"{prefix}__{label}__{slug}__{conversation_id}.html"
        html_path = threads_dir / filename
        json_path = json_dir / f"{prefix}__{label}__{slug}__{conversation_id}.json"
        is_cached = not args.force and conversation_id in cached_conversation_ids and not has_new_tweets(conversation_id)
        if not is_cached:
            render_thread_html(
                html_path,
                conversation_id,
                title,
                thread_type,
                label,
                tickers,
                tags,
                tldr,
                json_path,
                items,
                users,
                media,
                media_paths,
                search_counts.get(conversation_id, 0),
                root,
            )
        if not is_cached:
            json_path.write_text(
                json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "title": title,
                        "canonical_filename": filename,
                        "type": thread_type,
                        "primary_label": label,
                        "tickers": tickers,
                        "tags": tags,
                        "priority": "UNCLASSIFIED",
                        "tldr": tldr,
                        "completeness_status": "conversation_search_partial",
                        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "tweets": items,
                        "users": users,
                        "media": {k: v for k, v in media.items() if k in {mk for item in items for mk in media_keys(item)}},
                        "media_paths": media_paths,
                        "rate_limits": client.rate_limits,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        # For cached threads read captured_at from the existing JSON so
        # relative-time display in the index stays accurate across runs.
        if is_cached:
            try:
                captured_at = json.loads(json_path.read_text(encoding="utf-8")).get(
                    "captured_at", dt.datetime.now(dt.timezone.utc).isoformat()
                )
            except Exception:
                captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
        else:
            captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
        entries.append(
            {
                "type": thread_type,
                "title": title,
                "date": f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}",
                "captured_at": captured_at,
                "label": label,
                "tickers": tickers,
                "tags": tags,
                "conversation_id": conversation_id,
                "abs_path": str(html_path),
                "posts": len(items),
                "aj_posts": sum(1 for item in items if item.get("author_id") == AJ_USER_ID),
                "photos": sum(len(media_keys(item)) for item in items),
            }
        )

    # Include all cached threads that weren't in this run's conversation_ids
    # so the index always shows the full archive, not just the last N threads.
    processed_ids = {e["conversation_id"] for e in entries}
    for json_path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        conv_id = data.get("conversation_id")
        if not conv_id or conv_id in processed_ids:
            continue
        filename = data.get("canonical_filename", "")
        html_path = threads_dir / filename if filename else None
        if not html_path or not html_path.exists():
            continue
        # Date from filename prefix (YYYYMMDD__...) is the tweet date.
        # captured_at reflects script run time so we don't use it here.
        prefix = json_path.stem.split("__")[0]
        date = f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}" if len(prefix) == 8 else data.get("captured_at", "")[:10]
        entries.append(
            {
                "type": data.get("type", ""),
                "title": data.get("title", conv_id),
                "date": date,
                "captured_at": date,
                "label": data.get("primary_label", "UNKNOWN"),
                "tickers": data.get("tickers", []),
                "tags": data.get("tags", []),
                "conversation_id": conv_id,
                "abs_path": str(html_path),
                "posts": len(data.get("tweets", [])),
                "aj_posts": sum(1 for t in data.get("tweets", []) if t.get("author_id") == AJ_USER_ID),
                "photos": sum(len(media_keys(t)) for t in data.get("tweets", [])),
            }
        )

    render_all_indexes(root, entries)
    usage = write_usage_estimate(root, run_id, client)
    print(f"INDEX={root / 'indexes' / 'index.html'}")
    print(f"THREADS={len(entries)}")
    print(f"RAW_API_DIR={raw_dir}")
    print(f"MEDIA_DIR={media_dir}")
    print(f"API_CALLS={client.call_count}")
    print(f"UNIQUE_POST_READS_ESTIMATE={usage['unique_post_ids_returned']}")
    print(f"ESTIMATED_X_COST_USD={usage['estimated_cost_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
