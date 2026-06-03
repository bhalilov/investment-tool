"""Helpers for reading saved X raw API response archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def saved_raw_response(raw_path: Path) -> dict[str, Any]:
    wrapper = json.loads(raw_path.read_text(encoding="utf-8"))
    response = wrapper.get("response")
    return response if isinstance(response, dict) else wrapper


def raw_response_tweets(response: dict[str, Any]) -> list[dict[str, Any]]:
    tweets: list[dict[str, Any]] = []
    data = response.get("data")
    if isinstance(data, list):
        tweets.extend(item for item in data if isinstance(item, dict))
    elif isinstance(data, dict):
        tweets.append(data)
    includes = response.get("includes") or {}
    tweets.extend(item for item in includes.get("tweets") or [] if isinstance(item, dict))
    return tweets


def load_raw_api_archive(raw_root: Path) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict], dict[str, int]]:
    tweets: dict[str, dict] = {}
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}
    stats = {
        "raw_files": 0,
        "tweet_records": 0,
        "user_records": 0,
        "media_records": 0,
        "failed_raw_files": 0,
    }
    for raw_path in sorted(raw_root.glob("*/*.json")):
        stats["raw_files"] += 1
        try:
            response = saved_raw_response(raw_path)
        except Exception:
            stats["failed_raw_files"] += 1
            continue
        for tweet in raw_response_tweets(response):
            tweet_id = tweet.get("id")
            if tweet_id:
                tweets[str(tweet_id)] = tweet
                stats["tweet_records"] += 1
        includes = response.get("includes") or {}
        for user in includes.get("users") or []:
            user_id = user.get("id")
            if user_id:
                users[str(user_id)] = user
                stats["user_records"] += 1
        for item in includes.get("media") or []:
            key = item.get("media_key")
            if key:
                media[str(key)] = item
                stats["media_records"] += 1
    return tweets, users, media, stats
