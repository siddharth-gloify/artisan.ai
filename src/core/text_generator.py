"""Caption generation via OpenRouter (OpenAI-compatible API)."""

import json
import os
import re

from openai import OpenAI
from src.utils.logger import get_logger

log = get_logger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_HEADERS = {"HTTP-Referer": "https://postforge.app", "X-Title": "PostForge"}


def _client() -> OpenAI | None:
    key = os.getenv("OPENROUTER_TEXT_KEY")
    if not key:
        return None
    return OpenAI(base_url=_OPENROUTER_BASE, api_key=key)


def _parse_json_from_text(text: str) -> dict:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def generate_caption(prompt: str, fallback: dict) -> dict:
    client = _client()
    if not client:
        log.warning("OPENROUTER_TEXT_KEY not set — using fallback caption")
        return fallback

    model = os.getenv("OPENROUTER_TEXT_MODEL") or "deepseek/deepseek-chat"
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
            extra_headers=_HEADERS,
        )
        raw = response.choices[0].message.content or ""
        data = _parse_json_from_text(raw)
        return _validate_caption(data, fallback)
    except Exception as exc:
        log.error("OpenRouter text error (%s): %s", model, exc)
        return fallback


def _validate_caption(data: dict, fallback: dict) -> dict:
    headline = str(data.get("headline", fallback.get("headline", "")))[:60]
    body = str(data.get("body", fallback.get("body", "")))[:200]
    hashtags = data.get("hashtags", fallback.get("hashtags", []))
    if not isinstance(hashtags, list):
        hashtags = fallback.get("hashtags", [])
    return {"headline": headline, "body": body, "hashtags": [str(h) for h in hashtags[:7]]}
