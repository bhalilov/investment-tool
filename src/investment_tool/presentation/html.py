"""Shared HTML rendering helpers."""

from __future__ import annotations

import html
import re

from investment_tool.rules.tickers import KNOWN_TICKERS


URL_RE = re.compile(r"https?://[^\s<]+")


def display_token(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    words = re.split(r"[_\-\s]+", text)
    keep_upper = {"AI", "API", "X", "OCR", "P0", "P1", "P2", "P3", "P4", "IPO", "EV", "EPS", "PE"}
    out: list[str] = []
    for word in words:
        upper = word.upper()
        if upper in keep_upper or upper in KNOWN_TICKERS:
            out.append(upper)
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)


def linkify_text(text: str) -> str:
    """HTML-escape text while turning bare URLs into clickable links."""
    parts: list[str] = []
    last = 0
    for match in URL_RE.finditer(text):
        parts.append(html.escape(text[last : match.start()]))
        url = match.group(0).rstrip(".,)")
        trailing = match.group(0)[len(url) :]
        safe_url = html.escape(url, quote=True)
        parts.append(f'<a href="{safe_url}">{html.escape(url)}</a>{html.escape(trailing)}')
        last = match.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)
