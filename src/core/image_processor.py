"""
Image generation via OpenRouter — Gemini image models.

Response structure (OpenRouter-specific):
  choices[0].message.images[0].image_url.url  -> "data:image/png;base64,..."
  choices[0].message.content                  -> text description (ignored)

Falls back to Pillow gradient when key is missing or call fails.
"""

import base64
import os
from pathlib import Path

import httpx
from PIL import Image

from src.core.composition import create_gradient_background
from src.utils.logger import get_logger

log = get_logger(__name__)

_OPENROUTER_CHAT = "https://openrouter.ai/api/v1/chat/completions"
_HEADERS = {
    "HTTP-Referer": "https://postforge.app",
    "X-Title": "PostForge",
    "Content-Type": "application/json",
}

IMAGE_MODELS = {
    "normal": "google/gemini-2.5-flash-image",
    "pro":    "google/gemini-3.1-flash-image-preview",
    "max":    "google/gemini-3-pro-image-preview",
}
DEFAULT_TIER = "normal"


def resolve_model(tier: str | None) -> str:
    return IMAGE_MODELS.get(tier or DEFAULT_TIER, IMAGE_MODELS[DEFAULT_TIER])


async def generate_base_image(
    prompt: str,
    palette: dict,
    output_path: Path,
    tier: str = DEFAULT_TIER,
    width: int = 1080,
    height: int = 1350,
) -> bool:
    """Returns True if an AI image was saved, False if Pillow fallback was used."""
    key = os.getenv("OPENROUTER_IMAGE_KEY")
    if key:
        model = resolve_model(tier)
        success = await _gen_openrouter(prompt, output_path, key, model, width, height)
        if success:
            return True

    _gen_gradient_fallback(palette, output_path, width, height)
    return False


async def _gen_openrouter(
    prompt: str, output_path: Path, key: str, model: str,
    width: int, height: int,
) -> bool:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt[:2000]}],
            }
        ],
    }
    headers = {**_HEADERS, "Authorization": f"Bearer {key}"}

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(_OPENROUTER_CHAT, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()

        message = data["choices"][0]["message"]

        # ── Primary path: OpenRouter stores image in message.images ──────────
        images = message.get("images") or []
        if images:
            url = images[0].get("image_url", {}).get("url", "")
            if url.startswith("data:"):
                _save_data_url(url, output_path)
                _resize_to(output_path, width, height)
                log.info("Image saved via message.images (%s) -> %s", model, output_path)
                return True

        # ── Fallback: image embedded in content list ──────────────────────────
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    if url.startswith("data:"):
                        _save_data_url(url, output_path)
                    else:
                        async with httpx.AsyncClient(timeout=60) as c:
                            img_r = await c.get(url)
                            img_r.raise_for_status()
                            output_path.write_bytes(img_r.content)
                    _resize_to(output_path, width, height)
                    log.info("Image saved via content list (%s) -> %s", model, output_path)
                    return True

        log.warning("No image data found in response from %s", model)
        return False

    except Exception as exc:
        log.warning("OpenRouter image failed (%s): %s", model, exc)
        return False


def _save_data_url(data_url: str, path: Path) -> None:
    _, b64 = data_url.split(",", 1)
    path.write_bytes(base64.b64decode(b64))


def _resize_to(path: Path, width: int, height: int) -> None:
    """Cover-crop the saved image to the target canvas size.
    Scales to fill, then center-crops — never stretches/distorts the photo
    (models often return square images; a plain resize would warp faces)."""
    try:
        with Image.open(path) as img:
            if img.size != (width, height):
                img = img.convert("RGB")
                scale = max(width / img.width, height / img.height)
                new_w = max(width,  round(img.width * scale))
                new_h = max(height, round(img.height * scale))
                img = img.resize((new_w, new_h), Image.LANCZOS)
                left = (new_w - width) // 2
                top  = (new_h - height) // 2
                img = img.crop((left, top, left + width, top + height))
                img.save(str(path), "PNG")
    except Exception as exc:
        log.warning("Resize failed: %s", exc)


def _gen_gradient_fallback(palette: dict, output_path: Path, width: int, height: int) -> None:
    bg  = palette.get("background", "#111827")
    end = palette.get("gradient_end", palette.get("primary", "#1E3A5F"))
    img = create_gradient_background(width, height, bg, end)
    img.save(str(output_path), "PNG")
    log.info("Pillow gradient fallback -> %s", output_path)
