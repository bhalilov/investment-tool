"""X API client and low-level fetch/download helpers."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investment_tool.runtime.paths import portable_path
from investment_tool.runtime.reporting import report_event


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


@dataclass(frozen=True)
class ConversationSearchResult:
    result_count: int
    pages_requested: int
    pages_fetched: int
    has_more: bool
    missing_reference_ids: tuple[str, ...] = ()
    error_count: int = 0


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
        report_event("WARNING", "x-api", reason="token_refresh_failed", error=str(exc))
        return None
    access_token = data.get("access_token")
    if not access_token:
        report_event("WARNING", "x-api", reason="token_refresh_missing_access_token")
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
        try:
            self.max_rate_limit_retries = max(0, int(os.environ.get("X_MAX_RATE_LIMIT_RETRIES", "3")))
        except ValueError:
            self.max_rate_limit_retries = 3
            report_event("WARNING", "x-api", reason="invalid_max_rate_limit_retries", fallback=3)

    def get(self, path: str, params: dict[str, str | int] | None = None, label: str = "api") -> dict:
        return self._get(path, params, label, allow_refresh=True)

    def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        label: str = "api",
        allow_refresh: bool = True,
        rate_limit_retries: int = 0,
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
            if rate_limit_retries >= self.max_rate_limit_retries:
                report_event(
                    "ERROR",
                    "x-api",
                    reason="rate_limit_retries_exhausted",
                    label=label,
                    status=status,
                    retry=rate_limit_retries,
                    max_retries=self.max_rate_limit_retries,
                    reset_at=reset_note,
                )
                raise RuntimeError(
                    f"X API rate limit retry limit reached for {label}: "
                    f"{rate_limit_retries}/{self.max_rate_limit_retries}"
                )
            report_event(
                "WAITING",
                "x-api",
                reason="rate_limit",
                label=label,
                wait_seconds=wait_seconds,
                reset_at=reset_note,
                retry=rate_limit_retries + 1,
                max_retries=self.max_rate_limit_retries,
            )
            time.sleep(wait_seconds)
            return self._get(
                path,
                params,
                f"{label}_retry_after_rate_limit",
                allow_refresh=allow_refresh,
                rate_limit_retries=rate_limit_retries + 1,
            )
        if status == 401 and allow_refresh and self.refresh_callback:
            new_token = self.refresh_callback()
            if new_token:
                self.token = new_token
                return self._get(path, params, f"{label}_retry_after_refresh", allow_refresh=False)
        if status >= 400:
            report_event(
                "ERROR",
                "x-api",
                reason="http_error",
                label=label,
                status=status,
                error=json.dumps(data, ensure_ascii=False)[:500],
            )
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
    feed_user_id: str,
    pages: int,
    tweets: dict[str, dict],
    users: dict[str, dict],
    media: dict[str, dict],
    known_tweet_ids: set[str] | None = None,
    stop_after_known_streak: int = 0,
) -> list[str]:
    seed_ids: list[str] = []
    pagination_token: str | None = None
    known_tweet_ids = known_tweet_ids or set()
    known_streak = 0
    stop = False
    for page in range(pages):
        params = tweet_params(max_results=100)
        if pagination_token:
            params["pagination_token"] = pagination_token
        response = client.get(f"/users/{feed_user_id}/tweets", params, f"feed_timeline_page_{page + 1}")
        merge_response(response, tweets, users, media)
        for item in response.get("data") or []:
            tweet_id = item["id"]
            if tweet_id in known_tweet_ids:
                known_streak += 1
            else:
                known_streak = 0
            if stop_after_known_streak and known_streak >= stop_after_known_streak:
                stop = True
                break
            seed_ids.append(tweet_id)
        if stop:
            break
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
) -> ConversationSearchResult:
    count = 0
    next_token: str | None = None
    pages_fetched = 0
    missing_reference_ids: set[str] = set()
    error_count = 0
    for page in range(pages):
        params = tweet_params(query=f"conversation_id:{conversation_id}", max_results=100)
        if next_token:
            params["next_token"] = next_token
        response = client.get("/tweets/search/recent", params, f"conversation_{conversation_id}_page_{page + 1}")
        pages_fetched += 1
        count += len(response.get("data") or [])
        errors = response.get("errors") or []
        error_count += len(errors)
        for error in errors:
            detail = str(error.get("detail") or "")
            missing_id = str(error.get("resource_id") or error.get("value") or "")
            if missing_id and "referenced_tweets.id" in detail:
                missing_reference_ids.add(missing_id)
        merge_response(response, tweets, users, media)
        next_token = (response.get("meta") or {}).get("next_token")
        if not next_token:
            break
        time.sleep(0.2)
    return ConversationSearchResult(
        result_count=count,
        pages_requested=pages,
        pages_fetched=pages_fetched,
        has_more=bool(next_token),
        missing_reference_ids=tuple(sorted(missing_reference_ids)),
        error_count=error_count,
    )


def photo_media_path(media_dir: Path, key: str, item: dict[str, Any]) -> Path:
    url = item["url"]
    suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
    return media_dir / f"{key}{suffix}"


def download_photos(media: dict[str, dict], media_dir: Path, wanted_keys: set[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for key, item in media.items():
        if key not in wanted_keys:
            continue
        if item.get("type") != "photo" or not item.get("url"):
            continue
        url = item["url"]
        path = photo_media_path(media_dir, key, item)
        if not path.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "investment-tool/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    path.write_bytes(resp.read())
            except Exception as exc:
                report_event("WARNING", "x-api", reason="media_download_failed", media_key=key, error=str(exc))
                continue
        if path.exists():
            paths[key] = portable_path(path)
    return paths
