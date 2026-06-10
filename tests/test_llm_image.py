"""
Test 2 — OpenRouter image generation.
Tests: gemini-2.5-flash-image (normal tier) + Pillow gradient fallback.
Run: python -m pytest tests/test_llm_image.py -v -s
"""

import asyncio
import logging
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import pytest
from PIL import Image

from src.core.image_processor import generate_base_image, IMAGE_MODELS
from src.utils.constants import OUTPUT_DIR
from src.utils.helpers import ensure_dir

# ── Logger ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("test.llm_image")

# ── Fixtures ──────────────────────────────────────────────────────────────────
FIXTURES = Path(__file__).parent / "fixtures"
PALETTE = {
    "background":   "#0A1729",
    "primary":      "#00FF41",
    "secondary":    "#137DC5",
    "gradient_end": "#0F2A4A",
}
PROMPT = (
    "Dark minimalist background, subtle neon geometric lines, "
    "professional studio lighting, about AI startup, "
    "Instagram post format 4:5, high quality"
)


def _copy_to_output(src: Path, label: str) -> Path:
    ensure_dir(OUTPUT_DIR)
    dest = OUTPUT_DIR / f"test_{int(time.time())}_{label}.png"
    shutil.copy2(src, dest)
    log.info("Saved to output/ -> %s", dest.name)
    return dest


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_env_key_present():
    key = os.getenv("OPENROUTER_IMAGE_KEY", "")
    log.info("OPENROUTER_IMAGE_KEY present: %s", bool(key and key != "sk-or-v1-"))
    assert key and key != "sk-or-v1-", (
        "OPENROUTER_IMAGE_KEY is empty or placeholder — add your key to .env"
    )


def test_normal_tier():
    """gemini-2.5-flash-image — generate, validate, save to output/."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out = FIXTURES / "test_image_normal.png"
    if out.exists():
        out.unlink()

    model = IMAGE_MODELS["normal"]
    log.info("Model : %s", model)
    log.info("Sending prompt to OpenRouter...")

    t0 = time.time()
    used_llm = asyncio.run(generate_base_image(PROMPT, PALETTE, out, tier="normal"))
    elapsed = round(time.time() - t0, 2)

    log.info("Response in %.2fs | LLM used: %s", elapsed, used_llm)

    assert out.exists(), "Output file was not created"
    assert out.stat().st_size > 1000, "Output file looks empty"

    img = Image.open(out)
    log.info("Dimensions: %d x %d | Size: %.1f KB",
             img.width, img.height, out.stat().st_size / 1024)
    assert img.width > 0 and img.height > 0

    _copy_to_output(out, "normal")


def test_fallback_works_without_key(monkeypatch):
    """Pillow gradient fallback — no API key, must produce 1080x1350."""
    log.info("Testing Pillow fallback (no API key)...")
    monkeypatch.delenv("OPENROUTER_IMAGE_KEY", raising=False)

    FIXTURES.mkdir(parents=True, exist_ok=True)
    out = FIXTURES / "test_fallback.png"

    t0 = time.time()
    used_llm = asyncio.run(generate_base_image(PROMPT, PALETTE, out, tier="normal"))
    elapsed = round(time.time() - t0, 2)

    log.info("Fallback generated in %.2fs", elapsed)
    assert not used_llm, "Expected fallback, but LLM was used"
    assert out.exists()

    img = Image.open(out)
    log.info("Fallback dims: %d x %d", img.width, img.height)
    assert img.width == 1080
    assert img.height == 1350

    _copy_to_output(out, "fallback")
