#!/usr/bin/env python3
"""Probe X thread capture for a configured source account, replies, and image media."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from investment_tool.runtime.env import load_env
from investment_tool.runtime.config import SourceProfile, load_x_source_profile


API_BASE = "https://api.x.com/2"
SOURCE_PROFILE: SourceProfile = load_x_source_profile()
SOURCE_USERNAME = SOURCE_PROFILE.username
SOURCE_USER_ID = SOURCE_PROFILE.user_id


def configure_source(profile: SourceProfile) -> None:
    global SOURCE_PROFILE, SOURCE_USERNAME, SOURCE_USER_ID
    SOURCE_PROFILE = profile
    SOURCE_USERNAME = profile.username
    SOURCE_USER_ID = profile.user_id

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
MEDIA_FIELDS = ",".join(
    [
        "media_key",
        "type",
        "url",
        "preview_image_url",
        "width",
        "height",
        "alt_text",
        "variants",
    ]
)
USER_FIELDS = "id,username,name,verified,verified_type,protected"


class XClient:
    def __init__(self, token: str, raw_dir: Path) -> None:
        self.token = token
        self.raw_dir = raw_dir
        self.call_count = 0
        self.rate_limits: list[dict[str, str | None]] = []

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

        self.rate_limits.append(
            {
                "label": label,
                "status": str(status),
                "limit": headers.get("x-rate-limit-limit"),
                "remaining": headers.get("x-rate-limit-remaining"),
                "reset": headers.get("x-rate-limit-reset"),
            }
        )
        raw_path = self.raw_dir / f"{self.call_count:04d}_{safe_name(label)}_{status}.json"
        raw_path.write_text(
            json.dumps(
                {
                    "fetched_at": fetched_at,
                    "url": url,
                    "status": status,
                    "rate_limit": self.rate_limits[-1],
                    "response": data,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        if status >= 400:
            raise RuntimeError(f"X API error {status} for {label}: {json.dumps(data)[:500]}")
        return data


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)[:80]


def tweet_params(**extra: str | int) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "tweet.fields": TWEET_FIELDS,
        "expansions": EXPANSIONS,
        "media.fields": MEDIA_FIELDS,
        "user.fields": USER_FIELDS,
    }
    params.update(extra)
    return params


def merge_response(
    response: dict,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
) -> None:
    for tweet in response.get("data") or []:
        tweets[tweet["id"]] = tweet
    includes = response.get("includes") or {}
    for tweet in includes.get("tweets") or []:
        tweets[tweet["id"]] = tweet
    for user in includes.get("users") or []:
        users[user["id"]] = user
    for item in includes.get("media") or []:
        media[item["media_key"]] = item


def fetch_source_timeline(client: XClient, max_pages: int) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    tweets: dict[str, dict] = {}
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}
    pagination_token: str | None = None
    for page in range(max_pages):
        params = tweet_params(max_results=100)
        if pagination_token:
            params["pagination_token"] = pagination_token
        response = client.get(f"/users/{SOURCE_USER_ID}/tweets", params, f"source_timeline_page_{page + 1}")
        merge_response(response, tweets, users, media)
        pagination_token = (response.get("meta") or {}).get("next_token")
        if not pagination_token:
            break
    return tweets, users, media


def fetch_tweets_by_ids(
    client: XClient,
    ids: list[str],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    label: str,
) -> None:
    missing = [tweet_id for tweet_id in ids if tweet_id not in tweets]
    for i in range(0, len(missing), 100):
        chunk = missing[i : i + 100]
        if not chunk:
            continue
        response = client.get("/tweets", tweet_params(ids=",".join(chunk)), f"{label}_{i // 100 + 1}")
        merge_response(response, tweets, users, media)


def walk_parent_chains(
    client: XClient,
    seed_ids: list[str],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    depth_limit: int = 20,
) -> list[str]:
    missing: list[str] = []
    for seed_id in seed_ids:
        current = seed_id
        seen: set[str] = set()
        for _ in range(depth_limit):
            tweet = tweets.get(current)
            if not tweet:
                missing.append(current)
                break
            refs = tweet.get("referenced_tweets") or []
            parent_id = next((ref.get("id") for ref in refs if ref.get("type") == "replied_to"), None)
            if not parent_id or parent_id in seen:
                break
            seen.add(parent_id)
            if parent_id not in tweets:
                fetch_tweets_by_ids(client, [parent_id], tweets, users, media, "parent_lookup")
            current = parent_id
    return missing


def search_conversation(
    client: XClient,
    conversation_id: str,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    max_pages: int,
) -> int:
    count = 0
    next_token: str | None = None
    for page in range(max_pages):
        params = tweet_params(query=f"conversation_id:{conversation_id}", max_results=100)
        if next_token:
            params["next_token"] = next_token
        response = client.get("/tweets/search/recent", params, f"conversation_{conversation_id}_page_{page + 1}")
        count += len(response.get("data") or [])
        merge_response(response, tweets, users, media)
        next_token = (response.get("meta") or {}).get("next_token")
        if not next_token:
            break
    return count


def media_keys(tweet: dict) -> list[str]:
    return (tweet.get("attachments") or {}).get("media_keys") or []


def display_text(tweet: dict) -> str:
    note_text = ((tweet.get("note_tweet") or {}).get("text") or "").strip()
    if note_text:
        return note_text
    return tweet.get("text") or ""


def has_photo(tweet: dict, media: dict[str, dict]) -> bool:
    return any((media.get(key) or {}).get("type") == "photo" for key in media_keys(tweet))


def download_photos(media: dict[str, dict], out_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key, item in media.items():
        if item.get("type") != "photo" or not item.get("url"):
            continue
        url = item["url"]
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
        local_path = out_dir / f"{key}{suffix}"
        if local_path.exists():
            paths[key] = local_path
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "investment-tool-probe/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                local_path.write_bytes(resp.read())
            paths[key] = local_path
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: failed to download media {key}: {exc}", file=sys.stderr)
    return paths


def tweet_url(tweet_id: str) -> str:
    return f"https://x.com/{SOURCE_USERNAME}/status/{tweet_id}"


def render_html(
    out_path: Path,
    conversations: list[str],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    downloaded: dict[str, Path],
    conversation_search_counts: dict[str, int],
    rate_limits: list[dict[str, str | None]],
    source_timeline_pages: int,
) -> None:
    by_conv: dict[str, list[dict]] = {conv: [] for conv in conversations}
    for tweet in tweets.values():
        conv = tweet.get("conversation_id")
        if conv in by_conv:
            by_conv[conv].append(tweet)

    def author(tweet: dict) -> str:
        user = users.get(tweet.get("author_id"), {})
        username = user.get("username") or tweet.get("author_id") or "unknown"
        return f"@{username}"

    sections: list[str] = []
    for conv_id in conversations:
        items = sorted(by_conv[conv_id], key=lambda item: item.get("created_at") or "")
        source_count = sum(1 for item in items if item.get("author_id") == SOURCE_USER_ID)
        photo_count = sum(1 for item in items if has_photo(item, media))
        section = [
            f"<section><h2>Conversation {html.escape(conv_id)}</h2>",
            "<div class='meta'>",
            f"<strong>Total captured posts:</strong> {len(items)} &nbsp; ",
            f"<strong>Source posts captured:</strong> {source_count} &nbsp; ",
            f"<strong>Posts with photos:</strong> {photo_count} &nbsp; ",
            f"<strong>Conversation-search results:</strong> {conversation_search_counts.get(conv_id, 0)}",
            "</div>",
            (
                "<p class='warning'>Completeness note: this report combines source timeline polling, direct parent-chain lookups, "
                "and conversation search. X conversation search may omit protected source replies, so compare against x.com.</p>"
            ),
        ]
        for item in items:
            refs = item.get("referenced_tweets") or []
            ref_text = ", ".join(f"{ref.get('type')}:{ref.get('id')}" for ref in refs) or "none"
            classes = "tweet source" if item.get("author_id") == SOURCE_USER_ID else "tweet"
            metrics = item.get("public_metrics") or {}
            note_badge = " | full note_tweet rendered" if (item.get("note_tweet") or {}).get("text") else ""
            metrics_text = (
                f"replies: {metrics.get('reply_count', 'n/a')} | likes: {metrics.get('like_count', 'n/a')} "
                f"| bookmarks: {metrics.get('bookmark_count', 'n/a')}{note_badge}"
            )
            section.extend(
                [
                    f"<article class='{classes}'>",
                    "<div class='tweet-head'>",
                    f"<strong>{html.escape(author(item))}</strong>",
                    f"<span>{html.escape(item.get('created_at') or '')}</span>",
                    f"<a href='{tweet_url(item['id'])}'>open on X</a>",
                    "</div>",
                    f"<div class='tweet-id'>id {html.escape(item['id'])} | refs: {html.escape(ref_text)}</div>",
                    f"<div class='tweet-id'>{html.escape(metrics_text)}</div>",
                    f"<p>{html.escape(display_text(item))}</p>",
                ]
            )
            for key in media_keys(item):
                medium = media.get(key) or {}
                section.append(
                    f"<div class='media-meta'>media {html.escape(key)} | type {html.escape(str(medium.get('type')))} "
                    f"| {html.escape(str(medium.get('width')))}x{html.escape(str(medium.get('height')))}</div>"
                )
                path = downloaded.get(key)
                if path:
                    section.append(f"<img src='{path.as_uri()}' alt='downloaded X media {html.escape(key)}'>")
                elif medium.get("preview_image_url"):
                    section.append(f"<a href='{html.escape(medium['preview_image_url'])}'>preview image URL</a>")
            section.append("</article>")
        section.append("</section>")
        sections.append("\n".join(section))

    rate_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('label')))}</td>"
        f"<td>{html.escape(str(row.get('status')))}</td>"
        f"<td>{html.escape(str(row.get('limit')))}</td>"
        f"<td>{html.escape(str(row.get('remaining')))}</td>"
        f"<td>{html.escape(str(row.get('reset')))}</td>"
        "</tr>"
        for row in rate_limits
    )
    out_path.write_text(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>X Thread Media Probe</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #17202a; }}
    h1 {{ margin-bottom: 4px; }}
    section {{ border-top: 1px solid #ccd6dd; padding-top: 24px; margin-top: 28px; }}
    .meta, .tweet-id, .media-meta {{ color: #536471; font-size: 13px; }}
    .warning {{ background: #fff6cc; border: 1px solid #ead36a; padding: 10px 12px; border-radius: 6px; }}
    .tweet {{ border: 1px solid #d8e0e8; border-radius: 8px; padding: 14px; margin: 14px 0; max-width: 980px; }}
    .tweet.source {{ border-left: 5px solid #1d9bf0; }}
    .tweet-head {{ display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap; }}
    .tweet p {{ white-space: pre-wrap; line-height: 1.42; }}
    img {{ display: block; max-width: 900px; max-height: 760px; margin-top: 10px; border: 1px solid #ccd6dd; }}
    table {{ border-collapse: collapse; font-size: 13px; }}
    td, th {{ border: 1px solid #d8e0e8; padding: 6px 8px; }}
  </style>
</head>
<body>
  <h1>X Thread Media Probe</h1>
  <p class="meta">Generated {html.escape(dt.datetime.now().isoformat(timespec="seconds"))}. Source timeline pages fetched: {source_timeline_pages}.</p>
  <p class="warning">Purpose: compare these reconstructed threads against x.com for missing replies/media before building alerts.</p>
  {''.join(sections)}
  <section>
    <h2>API Calls / Rate Limits</h2>
    <table>
      <tr><th>Call</th><th>Status</th><th>Limit</th><th>Remaining</th><th>Reset</th></tr>
      {rate_rows}
    </table>
  </section>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-config", default="config/sources/x_accounts.json")
    parser.add_argument("--source-id", default="")
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--timeline-pages", type=int, default=3)
    parser.add_argument("--conversation-pages", type=int, default=5)
    parser.add_argument("--conversation-id")
    args = parser.parse_args()

    repo_env = Path(__file__).resolve().parents[1] / ".env"
    load_env(repo_env)
    configure_source(load_x_source_profile(args.source_config, args.source_id))
    token = os.environ.get("X_USER_ACCESS_TOKEN", "").strip()
    if not token:
        print("Missing X_USER_ACCESS_TOKEN in .env", file=sys.stderr)
        return 1

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = Path.home() / "investment-tool-data" / "probes" / f"x_thread_media_{stamp}"
    raw_dir = base_dir / "raw_api"
    media_dir = base_dir / "media"
    raw_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    client = XClient(token, raw_dir)
    tweets, users, media = fetch_source_timeline(client, args.timeline_pages)

    source_seed_ids = [tweet_id for tweet_id, tweet in tweets.items() if tweet.get("author_id") == SOURCE_USER_ID]
    walk_parent_chains(client, source_seed_ids, tweets, users, media)

    conversation_ids: list[str] = []
    if args.conversation_id:
        conversation_ids = [args.conversation_id]
        fetch_tweets_by_ids(client, [args.conversation_id], tweets, users, media, "requested_conversation_root")
    else:
        for tweet in sorted(tweets.values(), key=lambda item: item.get("created_at") or "", reverse=True):
            conv = tweet.get("conversation_id")
            if not conv or conv in conversation_ids:
                continue
            # Prefer conversations where we already see media or multiple local posts.
            conv_items = [item for item in tweets.values() if item.get("conversation_id") == conv]
            if any(media_keys(item) for item in conv_items) or len(conv_items) > 1:
                conversation_ids.append(conv)
            if len(conversation_ids) >= args.threads:
                break

        if len(conversation_ids) < args.threads:
            for tweet in sorted(tweets.values(), key=lambda item: item.get("created_at") or "", reverse=True):
                conv = tweet.get("conversation_id")
                if conv and conv not in conversation_ids:
                    conversation_ids.append(conv)
                if len(conversation_ids) >= args.threads:
                    break

    conversation_search_counts: dict[str, int] = {}
    for conv in conversation_ids:
        conversation_search_counts[conv] = search_conversation(
            client, conv, tweets, users, media, args.conversation_pages
        )
        conv_ids = [tweet_id for tweet_id, tweet in tweets.items() if tweet.get("conversation_id") == conv]
        walk_parent_chains(client, conv_ids, tweets, users, media)
        time.sleep(0.2)

    downloaded = download_photos(media, media_dir)
    report_path = base_dir / "thread_media_probe.html"
    render_html(
        report_path,
        conversation_ids,
        tweets,
        users,
        media,
        downloaded,
        conversation_search_counts,
        client.rate_limits,
        args.timeline_pages,
    )

    print(f"REPORT={report_path}")
    print(f"CONVERSATIONS={','.join(conversation_ids)}")
    print(f"TWEETS_CAPTURED={len(tweets)}")
    print(f"MEDIA_OBJECTS={len(media)}")
    print(f"PHOTOS_DOWNLOADED={len(downloaded)}")
    print(f"API_CALLS={client.call_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
