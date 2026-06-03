"""Shared OpenAI API helpers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


OPENAI_API_BASE = "https://api.openai.com/v1"


def extract_response_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    chunks: list[str] = []
    for output in response.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks)


def call_responses_json(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_content: list[dict[str, Any]],
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int,
    timeout: int = 90,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
        "max_output_tokens": max_output_tokens,
    }
    response = request_json(
        "POST",
        "/responses",
        api_key=api_key,
        body=payload,
        timeout=timeout,
    )
    text = extract_response_text(response)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI response was not valid JSON: {text[:500]}") from exc
    usage = response.get("usage") or {}
    parsed["_model"] = model
    parsed["_response_id"] = response.get("id")
    parsed["_input_tokens"] = usage.get("input_tokens")
    parsed["_output_tokens"] = usage.get("output_tokens")
    return parsed, response


def request_json(
    method: str,
    path: str,
    *,
    api_key: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    api_base: str = OPENAI_API_BASE,
) -> dict[str, Any]:
    data = None
    request_headers = {"Authorization": f"Bearer {api_key}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(
        api_base.rstrip("/") + path,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API {method} {path} failed with {exc.code}: {raw[:1000]}") from exc
    return json.loads(raw) if raw else {}
