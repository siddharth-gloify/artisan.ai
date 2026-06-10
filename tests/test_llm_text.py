"""
Test 1 — OpenRouter text (caption) generation.
Run: python -m pytest tests/test_llm_text.py -v -s
"""

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import pytest
from src.core.text_generator import generate_caption

# ── Logger ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("test.llm_text")

# ── Fixtures ──────────────────────────────────────────────────────────────────
FALLBACK = {
    "headline": "FALLBACK HEADLINE",
    "body": "This is a fallback body.",
    "hashtags": ["#fallback"],
}

SARCASTIC_PROMPT = """Write a sarcastic, witty Instagram caption about: AI startup launch
Industry context: tech/software/AI

Rules:
- Be clever and ironic, not mean-spirited
- Max 150 characters for body
- Max 8 words for headline
- 3-5 relevant hashtags

Return ONLY valid JSON:
{"headline": "short punchy headline", "body": "the caption body", "hashtags": ["#tag1", "#tag2", "#tag3"]}"""


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_env_key_present():
    key = os.getenv("OPENROUTER_TEXT_KEY", "")
    log.info("OPENROUTER_TEXT_KEY present: %s", bool(key and key != "sk-or-v1-"))
    assert key and key != "sk-or-v1-", (
        "OPENROUTER_TEXT_KEY is empty or placeholder — add your key to .env"
    )


def test_caption_returns_dict():
    log.info("Calling LLM for caption (sarcastic tone)...")
    t0 = time.time()
    result = generate_caption(SARCASTIC_PROMPT, FALLBACK)
    elapsed = round(time.time() - t0, 2)

    log.info("Response in %.2fs", elapsed)
    log.info("headline : %s", result["headline"])
    log.info("body     : %s", result["body"])
    log.info("hashtags : %s", result["hashtags"])

    assert isinstance(result, dict)


def test_caption_has_required_keys():
    result = generate_caption(SARCASTIC_PROMPT, FALLBACK)
    for key in ("headline", "body", "hashtags"):
        assert key in result, f"Missing key: {key}"
        log.info("key '%s': OK (%s chars)", key, len(str(result[key])))


def test_caption_is_not_fallback():
    """Confirm the LLM actually responded (not just the hardcoded fallback)."""
    result = generate_caption(SARCASTIC_PROMPT, FALLBACK)
    log.info("Checking result is not fallback...")
    assert result["headline"] != FALLBACK["headline"], (
        "Got fallback — check OPENROUTER_TEXT_KEY and model name"
    )
    log.info("Confirmed: real LLM response received")


def test_caption_lengths():
    result = generate_caption(SARCASTIC_PROMPT, FALLBACK)
    log.info("headline len : %d / 60", len(result["headline"]))
    log.info("body len     : %d / 200", len(result["body"]))
    log.info("hashtag count: %d", len(result["hashtags"]))

    assert len(result["headline"]) <= 60, "Headline too long"
    assert len(result["body"]) <= 200, "Body too long"
    assert isinstance(result["hashtags"], list)
    assert 1 <= len(result["hashtags"]) <= 7
