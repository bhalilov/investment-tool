"""Source-neutral ticker parsing backed by the configured ticker registry."""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path


DEFAULT_TICKER_REGISTRY_FILE = Path("config/ticker_registry.json")
BROAD_INDEX_TICKERS = {"SPY", "QQQ"}
TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_ticker_registry(path: str | Path | None = None) -> tuple[dict[str, str], set[str]]:
    configured = os.environ.get("TICKER_REGISTRY_FILE", "").strip()
    resolved = Path(path).expanduser() if path else (Path(configured).expanduser() if configured else Path.cwd() / DEFAULT_TICKER_REGISTRY_FILE)
    if not resolved.exists() and not path and not configured:
        resolved = project_root() / DEFAULT_TICKER_REGISTRY_FILE
    alias_to_symbol: dict[str, str] = {}
    symbols: set[str] = set()
    if not resolved.exists():
        return alias_to_symbol, symbols
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN: Could not read ticker registry {resolved}: {exc}", file=sys.stderr)
        return alias_to_symbol, symbols
    for raw_symbol, raw_aliases in (data.get("symbols") or {}).items():
        symbol = str(raw_symbol).upper().strip()
        if not symbol:
            continue
        symbols.add(symbol)
        alias_to_symbol[symbol.lower()] = symbol
        alias_to_symbol[symbol] = symbol
        for alias in raw_aliases or []:
            alias_text = str(alias).strip()
            if alias_text:
                alias_to_symbol[alias_text.lower()] = symbol
                alias_to_symbol[alias_text.upper()] = symbol
    return alias_to_symbol, symbols


TICKER_ALIASES, KNOWN_TICKERS = load_ticker_registry()


def normalize_ticker(value: str | None, aliases: dict[str, str] | None = None, known: set[str] | None = None) -> str:
    if not value:
        return "UNKNOWN"
    raw = str(value).strip()
    upper = raw.upper()
    if upper in {"NONE", "NULL", "N/A", "NA", "NO SPECIFIC TICKER", "NO SPECIFIC STOCK"}:
        return "UNKNOWN"
    aliases = aliases or TICKER_ALIASES
    known = known or KNOWN_TICKERS
    return aliases.get(upper) or aliases.get(raw.lower()) or (upper if upper in known else "UNKNOWN")


def extract_tickers(
    text: str,
    aliases: dict[str, str] | None = None,
    known: set[str] | None = None,
    broad_index_tickers: set[str] | None = None,
) -> list[str]:
    aliases = aliases or TICKER_ALIASES
    known = known or KNOWN_TICKERS
    broad_index_tickers = broad_index_tickers or BROAD_INDEX_TICKERS
    explicit = [normalize_ticker(ticker, aliases, known) for ticker in TICKER_RE.findall(text or "")]
    explicit = [ticker for ticker in explicit if ticker != "UNKNOWN"]
    lower = (text or "").lower()
    inferred = [
        symbol
        for alias, symbol in aliases.items()
        if alias
        and alias.lower() == alias
        and re.search(rf"\b{re.escape(alias)}\b", lower)
        and symbol not in broad_index_tickers
    ]
    return list(dict.fromkeys(inferred + explicit))


def ticker_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]


def is_example_only_ticker_sentence(sentence: str) -> bool:
    lower = sentence.lower()
    example_markers = (
        "for example",
        "eg ",
        "e.g",
        "for instance",
        "one example",
        "just one example",
    )
    risk_markers = (
        "black swan",
        "would likely get crushed",
        "would get crushed",
        "many semiconductor stocks",
        "many other",
        "there are many others",
    )
    return any(marker in lower for marker in example_markers) or any(marker in lower for marker in risk_markers)


def extract_subject_tickers(text: str) -> list[str]:
    subject_tickers: list[str] = []
    for sentence in ticker_sentences(text):
        sentence_tickers = extract_tickers(sentence)
        if not sentence_tickers:
            continue
        if is_example_only_ticker_sentence(sentence):
            continue
        subject_tickers.extend(sentence_tickers)
    return list(dict.fromkeys(subject_tickers))


def ticker_bucket_payload(tickers: list[str]) -> dict[str, object]:
    normalized = [normalize_ticker(ticker) for ticker in tickers]
    normalized = [ticker for ticker in normalized if ticker != "UNKNOWN"]
    normalized = list(dict.fromkeys(normalized))
    if len(normalized) == 1:
        return {"primary_ticker": normalized[0]}
    if len(normalized) > 1:
        return {"mentioned_only_tickers": normalized}
    return {}
