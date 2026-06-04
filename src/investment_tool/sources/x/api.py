"""X API client and low-level fetch/download helpers."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


API_BASE = "https://api.x.com/2"
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


def safe_slug(value: str, fallback: str = "thread") -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:90] or fallback


def update_env_values(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    updated: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _ = line.split("=", 1)
            if key in updates:
                updated.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        updated.append(line)
    for key, value in updates.items():
        if key not in seen:
            updated.append(f"{key}={value}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def refresh_x_user_token(env_path: Path) -> str | None:
    client_id = os.environ.get("X_CLIENT_ID", "").strip()
    client_secret = os.environ.get("X_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("X_USER_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        return None
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
    ).encode("utf-8")
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        "https://api.x.com/2/oauth2/token",
        data=body,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"WARN: X token refresh failed: {exc}", file=sys.stderr)
        return None
    access_token = data.get("access_token")
    if not access_token:
        print("WARN: X token refresh response did not include access token", file=sys.stderr)
        return None
    new_refresh = data.get("refresh_token") or refresh_token
    os.environ["X_USER_ACCESS_TOKEN"] = access_token
    os.environ["X_USER_REFRESH_TOKEN"] = new_refresh
    update_env_values(env_path, {"X_USER_ACCESS_TOKEN": access_token, "X_USER_REFRESH_TOKEN": new_refresh})
    return access_token


def tweet_params(**extra: str | int) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "tweet.fields": TWEET_FIELDS,
        "expansions": EXPANSIONS,
        "media.fields": MEDIA_FIELDS,
        "user.fields": USER_FIELDS,
    }
    params.update(extra)
    return params


class XClient:
    def __init__(self, token: str, raw_dir: Path, refresh_callback=None) -> None:
        self.token = token
        self.raw_dir = raw_dir
        self.refresh_callback = refresh_callback
        self.call_count = 0
        self.rate_limits: list[dict[str, str | None]] = []
        self.post_ids_returned: set[str] = set()

    def get(self, path: str, params: dict[str, str | int] | None = None, label: str = "api") -> dict:
        return self._get(path, params, label, allow_refresh=True)

    def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        label: str = "api",
        allow_refresh: bool = True,
    ) -> dict:
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
        if status == 429:
            reset = headers.get("x-rate-limit-reset")
            try:
                wait_seconds = max(5, int(reset or "0") - int(time.time()) + 2)
            except ValueError:
                wait_seconds = 60
            reset_note = (
                dt.datetime.fromtimestamp(int(reset), dt.timezone.utc).isoformat()
                if reset and reset.isdigit()
                else "unknown"
            )
            print(
                f"RATE_LIMIT_WAIT label={label} wait_seconds={wait_seconds} reset_at={reset_note}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait_seconds)
            return self._get(path, params, f"{label}_retry_after_rate_limit", allow_refresh=allow_refresh)
        if status == 401 and allow_refresh and self.refresh_callback:
            new_token = self.refresh_callback()
            if new_token:
                self.token = new_token
                return self._get(path, params, f"{label}_retry_after_refresh", allow_refresh=False)
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


def fetch_tweets_by_ids_even_if_cached(
    client: XClient,
    ids: list[str],
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    label: str,
) -> None:
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        if not chunk:
            continue
        response = client.get("/tweets", tweet_params(ids=",".join(chunk)), f"{label}_{i // 100 + 1}")
        merge_response(response, tweets, users, media)


def fetch_timeline(
    client: XClient,
    source_user_id: str,
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
        response = client.get(f"/users/{source_user_id}/tweets", params, f"source_timeline_page_{page + 1}")
        merge_response(response, tweets, users, media)
        for item in response.get("data") or []:
            seed_ids.append(item["id"])
        pagination_token = (response.get("meta") or {}).get("next_token")
        if not pagination_token:
            break
    return seed_ids


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
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    path.write_bytes(resp.read())
            except Exception as exc:
                print(f"WARN: Could not download media {key}: {exc}", file=sys.stderr)
                continue
        if path.exists():
            paths[key] = str(path)
    return paths
