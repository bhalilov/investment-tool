"""Shared progress reporting for long-running investment-tool jobs."""

from __future__ import annotations

import datetime as dt
import os
import random
import time
from collections.abc import Mapping
from typing import Any


# Decorative only. Avoid words that are common dev/git/runtime terms
# such as build, filter, branch, commit, push, pull, serve, package, tag.
VIBE_WORDS = [
    "shaking",
    "stirring",
    "muddling",
    "straining",
    "jiggering",
    "swizzling",
    "zesting",
    "dry-shaking",
    "fine-straining",
    "free-pouring",
    "garnishing",
    "chilling",
    "pouring",
    "crushing",
    "pressing",
    "fermenting",
    "racking",
    "fining",
    "cellaring",
    "bottling",
    "corking",
    "decanting",
    "destemming",
    "lees-stirring",
    "cold-soaking",
    "barreling",
    "malting",
    "mashing",
    "lautering",
    "sparging",
    "whirlpooling",
    "kraeusening",
    "conditioning",
    "hopping",
    "dry-hopping",
    "vorlaufing",
    "mashout",
    "pitching",
    "medu-minding",
    "ealu-pouring",
    "beor-brewing",
    "mazer-filling",
    "wassailing",
]


OPENAI_PRICE_PER_MILLION = {
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-4.1-nano": (0.10, 0.40),
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def compact_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def estimate_openai_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    env_prefix = "OPENAI_PRICE_" + "".join(ch if ch.isalnum() else "_" for ch in model.upper())
    input_price = os.environ.get(f"{env_prefix}_INPUT_PER_MILLION")
    output_price = os.environ.get(f"{env_prefix}_OUTPUT_PER_MILLION")
    if input_price and output_price:
        try:
            return round((input_tokens / 1_000_000) * float(input_price) + (output_tokens / 1_000_000) * float(output_price), 6)
        except ValueError:
            return None
    prices = OPENAI_PRICE_PER_MILLION.get(model)
    if not prices:
        return None
    in_price, out_price = prices
    return round((input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price, 6)


class JobReporter:
    def __init__(self, job: str, total: int | None = None, every_items: int = 10, every_seconds: float = 30.0) -> None:
        self.job = job
        self.total = total
        self.every_items = max(1, every_items)
        self.every_seconds = max(1.0, every_seconds)
        self.started_at = time.monotonic()
        self.started_at_iso = utc_now()
        self.last_checkpoint_at = self.started_at
        self.rng = random.Random(f"{job}:{self.started_at_iso}")

    def vibe(self) -> str:
        return self.rng.choice(VIBE_WORDS)

    def emit(self, event: str, **fields: Any) -> None:
        payload = {
            "vibe": self.vibe(),
            "job": self.job,
            "elapsed": compact_duration(time.monotonic() - self.started_at),
            **fields,
        }
        print(format_report_line(event, payload), flush=True)

    def start(self, **fields: Any) -> None:
        self.emit("START", started_at=self.started_at_iso, total=self.total if self.total is not None else "", **fields)

    def checkpoint(self, processed: int | None = None, force: bool = False, **fields: Any) -> None:
        now = time.monotonic()
        if not force and processed is not None:
            if processed % self.every_items != 0 and now - self.last_checkpoint_at < self.every_seconds:
                return
        elif not force and now - self.last_checkpoint_at < self.every_seconds:
            return
        self.last_checkpoint_at = now
        if processed is not None:
            fields.setdefault("processed", processed)
            if self.total is not None:
                fields.setdefault("total", self.total)
                if processed:
                    rate = processed / max(0.001, now - self.started_at)
                    remaining = max(0, self.total - processed)
                    fields.setdefault("eta", compact_duration(remaining / max(0.001, rate)))
        self.emit("CHECKPOINT", **fields)

    def checkpoint_stats(
        self,
        stats: Mapping[str, Any],
        processed: int | None = None,
        force: bool = False,
        token_model: str | None = None,
        **fields: Any,
    ) -> None:
        payload = {**stats, **fields}
        if token_model:
            payload.update(cost_fields(token_model, payload))
        self.checkpoint(processed=processed, force=force, **payload)

    def done(self, **fields: Any) -> None:
        self.emit("DONE", finished_at=utc_now(), **fields)

    def done_stats(self, stats: Mapping[str, Any], token_model: str | None = None, **fields: Any) -> None:
        payload = {**stats, **fields}
        if token_model:
            payload.update(cost_fields(token_model, payload))
        self.done(**payload)

    def fail(self, **fields: Any) -> None:
        self.emit("FAILED", finished_at=utc_now(), **fields)


def start_reporter(
    job: str,
    total: int | None = None,
    every_items: int = 10,
    every_seconds: float = 30.0,
    **fields: Any,
) -> JobReporter:
    reporter = JobReporter(job, total=total, every_items=every_items, every_seconds=every_seconds)
    reporter.start(**fields)
    return reporter


def cost_fields(model: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    input_tokens = int(fields.get("input_tokens") or fields.get("openai_input_tokens") or 0)
    output_tokens = int(fields.get("output_tokens") or fields.get("openai_output_tokens") or 0)
    return {"estimated_cost_usd": estimate_openai_cost_usd(model, input_tokens, output_tokens)}


def format_report_line(event: str, fields: Mapping[str, Any]) -> str:
    vibe = str(fields.get("vibe") or "").upper()
    parts = []
    for key, value in fields.items():
        if key == "vibe":
            continue
        if value is None:
            continue
        text = str(value).replace("\n", "\\n")
        if " " in text:
            text = '"' + text.replace('"', '\\"') + '"'
        parts.append(f"{key}={text}")
    prefix = f"[{vibe}] " if vibe else ""
    return f"{prefix}{event} " + " ".join(parts)
