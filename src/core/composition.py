"""Pillow composition engine — the heart of PostForge."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from src.utils.constants import (
    FONTS_DIR, WINDOWS_FONT_DIR, LINUX_FONT_DIRS,
    POST_WIDTH, POST_HEIGHT, TEXT_PADDING, MAX_TEXT_WIDTH,
)
from src.utils.helpers import hex_to_rgb, hex_to_rgba, clamp
from src.utils.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------

_font_cache: dict[str, ImageFont.FreeTypeFont] = {}

_SEARCH_DIRS: list[Path] = [FONTS_DIR, WINDOWS_FONT_DIR] + LINUX_FONT_DIRS


def _find_font_file(filename: str) -> Optional[Path]:
    for directory in _SEARCH_DIRS:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    cache_key = f"{filename}:{size}"
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    path = _find_font_file(filename)
    if path:
        try:
            font = ImageFont.truetype(str(path), size)
            _font_cache[cache_key] = font
            return font
        except Exception:
            pass

    # PIL default (bitmap — no size control, but always available)
    font = ImageFont.load_default()
    return font


def get_font(font_config: dict, role: str, size: int) -> ImageFont.FreeTypeFont:
    """role: 'headline' | 'body'"""
    primary = font_config.get(f"{role}_file", "arial.ttf")
    fallback = font_config.get(f"fallback_{role}", "arial.ttf")

    path = _find_font_file(primary)
    if path:
        return _load_font(primary, size)
    return _load_font(fallback, size)


# ---------------------------------------------------------------------------
# Background generation
# ---------------------------------------------------------------------------

def create_gradient_background(
    width: int, height: int, color_start: str, color_end: str
) -> Image.Image:
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    r1, g1, b1 = hex_to_rgb(color_start)
    r2, g2, b2 = hex_to_rgb(color_end)
    for y in range(height):
        t = y / height
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def create_solid_background(width: int, height: int, color: str) -> Image.Image:
    r, g, b = hex_to_rgb(color)
    return Image.new("RGB", (width, height), (r, g, b))


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def draw_text_block(
    canvas: Image.Image,
    text: str,
    center_x: int,
    top_y: int,
    font,
    color: str,
    max_width: int = MAX_TEXT_WIDTH,
    line_gap: int = 10,
) -> int:
    """Draw wrapped, horizontally-centred text. Returns the y after the last line."""
    if not text.strip():
        return top_y

    draw = ImageDraw.Draw(canvas)
    lines = _wrap_text(draw, text, font, max_width)
    if not lines:
        return top_y

    try:
        bbox_sample = draw.textbbox((0, 0), "Ag", font=font)
        line_height = bbox_sample[3] - bbox_sample[1]
    except Exception:
        line_height = font.size if hasattr(font, "size") else 20

    r, g, b = hex_to_rgb(color)
    fill = (r, g, b, 255)

    current_y = top_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = center_x - text_w // 2
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += line_height + line_gap

    return current_y


# ---------------------------------------------------------------------------
# Asset pasting
# ---------------------------------------------------------------------------

def paste_asset(
    canvas: Image.Image,
    asset_path: Path,
    x: int,
    y: int,
    target_w: Optional[int] = None,
    target_h: Optional[int] = None,
    opacity: float = 1.0,
) -> None:
    """Paste an asset at (x, y).  If target_w / target_h are given the asset is
    scaled to fit within those bounds while preserving its aspect ratio."""
    if not asset_path.exists():
        return
    try:
        asset = Image.open(asset_path).convert("RGBA")
        if target_w or target_h:
            orig_w, orig_h = asset.size
            if target_w and target_h:
                scale = min(target_w / orig_w, target_h / orig_h)
            elif target_w:
                scale = target_w / orig_w
            else:
                scale = target_h / orig_h
            new_w = max(1, round(orig_w * scale))
            new_h = max(1, round(orig_h * scale))
            asset = asset.resize((new_w, new_h), Image.LANCZOS)
        if opacity < 1.0:
            r, g, b, a = asset.split()
            a = a.point(lambda p: int(p * opacity))
            asset.putalpha(a)
        canvas.paste(asset, (x, y), asset)
    except Exception as exc:
        log.warning("Could not paste asset %s: %s", asset_path, exc)


# ---------------------------------------------------------------------------
# Split layout (up/down): solid-color top zone + photo bottom zone
# ---------------------------------------------------------------------------

def _compose_split_layout(
    session: dict,
    style_cfg: dict,
    palette: dict,
    font_cfg: dict,
    base_path: Path,
    session_dir: Path,
    width: int,
    height: int,
) -> Image.Image:
    PADDING = 64
    LOGO_MAX_W = 130
    TAG_RADIUS = 22
    TAG_PAD_X, TAG_PAD_Y = 22, 10

    photo_split = style_cfg.get("photo_split", 0.42)
    photo_y = int(height * photo_split)

    bg_color = palette.get("background", "#1E64DC")
    r, g, b = hex_to_rgb(bg_color)
    canvas = Image.new("RGBA", (width, height), (r, g, b, 255))

    # Paste AI photo into bottom zone, center-cropped
    if base_path.exists():
        try:
            photo = Image.open(base_path).convert("RGB")
            photo_h = height - photo_y
            aspect = photo.width / photo.height
            target_h = max(photo_h, int(width / aspect))
            photo = photo.resize((width, target_h), Image.LANCZOS)
            crop_top = (target_h - photo_h) // 2
            photo = photo.crop((0, crop_top, width, crop_top + photo_h))
            canvas.paste(photo.convert("RGBA"), (0, photo_y))
        except Exception as exc:
            log.warning("Split layout: could not paste photo: %s", exc)

    draw = ImageDraw.Draw(canvas)

    # Tag pill (top-left)
    tag_layer = session.get("tag_layer", {})
    tag_text = str(tag_layer.get("text", "")).upper().strip()
    tag_bottom_y = PADDING
    if tag_text and tag_layer.get("visible", True):
        pill_bg = tag_layer.get("bg_color", palette.get("accent", "#B48C3C"))
        pill_fg = tag_layer.get("text_color", "#FFFFFF")
        font_tag = get_font(font_cfg, "body", tag_layer.get("font_size", 26))
        bbox = draw.textbbox((0, 0), tag_text, font=font_tag)
        tag_w = bbox[2] - bbox[0] + TAG_PAD_X * 2
        tag_h = bbox[3] - bbox[1] + TAG_PAD_Y * 2
        try:
            draw.rounded_rectangle(
                [PADDING, PADDING, PADDING + tag_w, PADDING + tag_h],
                radius=TAG_RADIUS,
                fill=hex_to_rgb(pill_bg),
            )
        except AttributeError:
            draw.rectangle(
                [PADDING, PADDING, PADDING + tag_w, PADDING + tag_h],
                fill=hex_to_rgb(pill_bg),
            )
        draw.text(
            (PADDING + TAG_PAD_X, PADDING + TAG_PAD_Y - bbox[1]),
            tag_text,
            font=font_tag,
            fill=(*hex_to_rgb(pill_fg), 255),
        )
        tag_bottom_y = PADDING + tag_h

    # Logo (top-right)
    ll = session.get("logo_layer", {})
    if session.get("has_logo") and ll.get("visible", True):
        logo_path = session_dir / "assets" / "logo.png"
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert("RGBA")
                max_w = ll.get("width", 120)
                max_h = ll.get("height", 120)
                scale = min(max_w / logo.width, max_h / logo.height)
                logo = logo.resize(
                    (max(1, round(logo.width * scale)), max(1, round(logo.height * scale))),
                    Image.LANCZOS,
                )
                lx = ll.get("x", width - PADDING - logo.width)
                ly = ll.get("y", PADDING)
                canvas.paste(logo, (lx, ly), mask=logo.split()[3])
            except Exception as exc:
                log.warning("Split layout: could not paste logo: %s", exc)

    # Headline — left-aligned in top zone
    text_y = float(tag_bottom_y + 52)
    max_text_w = width - PADDING * 2
    headline_layer = session.get("headline_layer", {})
    if headline_layer.get("visible", True) and headline_layer.get("text"):
        hl_color = headline_layer.get("color", palette.get("text_primary", "#FFFFFF"))
        _hl_sz = headline_layer.get("font_size", 72)
        font_hl = (_load_font(headline_layer["font_file"], _hl_sz)
                   if headline_layer.get("font_file") else get_font(font_cfg, "headline", _hl_sz))
        hl_lines = _wrap_text(draw, headline_layer["text"], font_hl, max_text_w)
        try:
            sb = draw.textbbox((0, 0), "Ag", font=font_hl)
            hl_line_h = (sb[3] - sb[1]) * 1.12
        except Exception:
            hl_line_h = getattr(font_hl, "size", 72) * 1.12
        for line in hl_lines:
            draw.text((PADDING, int(text_y)), line, font=font_hl,
                      fill=(*hex_to_rgb(hl_color), 255))
            text_y += hl_line_h
        text_y += 36

    # Body/subline — left-aligned
    body_layer = session.get("body_layer", {})
    if body_layer.get("visible", True) and body_layer.get("text"):
        body_color = body_layer.get("color", palette.get("text_secondary", "#CCCCCC"))
        _body_sz = body_layer.get("font_size", 36)
        font_body = (_load_font(body_layer["font_file"], _body_sz)
                     if body_layer.get("font_file") else get_font(font_cfg, "body", _body_sz))
        body_lines = _wrap_text(draw, body_layer["text"], font_body, max_text_w)
        try:
            sb = draw.textbbox((0, 0), "Ag", font=font_body)
            body_line_h = (sb[3] - sb[1]) * 1.3
        except Exception:
            body_line_h = getattr(font_body, "size", 36) * 1.3
        for line in body_lines:
            draw.text((PADDING, int(text_y)), line, font=font_body,
                      fill=(*hex_to_rgb(body_color), 255))
            text_y += body_line_h

    return canvas


# ---------------------------------------------------------------------------
# Main compose
# ---------------------------------------------------------------------------

def compose_post(session: dict, config: dict, session_dir: Path) -> Path:
    """
    Full composition pipeline.
    Returns path to the saved composed.png.
    """
    style_cfg = config["image_styles"].get(session["image_style"], {})
    palette = config["color_palettes"].get(session["palette_id"], {})
    font_cfg = config["font_styles"].get(session["font_style"], {})

    width, height = POST_WIDTH, POST_HEIGHT

    # ── 1. Base image ────────────────────────────────────────────────────────
    base_path = session_dir / "base_image.png"

    # Split layout takes a completely different code path
    if style_cfg.get("layout") == "split":
        canvas = _compose_split_layout(
            session, style_cfg, palette, font_cfg,
            base_path, session_dir, width, height,
        )
        out = canvas.convert("RGB")
        out_path = session_dir / "composed.png"
        out.save(str(out_path), "PNG", optimize=False)
        log.info("Composed image saved -> %s", out_path)
        return out_path

    if base_path.exists():
        canvas = Image.open(base_path).convert("RGBA")
        canvas = canvas.resize((width, height), Image.LANCZOS)
    else:
        bg_color = palette.get("background", "#111111")
        gradient_end = palette.get("gradient_end", bg_color)
        bg = create_gradient_background(width, height, bg_color, gradient_end)
        canvas = bg.convert("RGBA")

    # ── 2. Colour overlay ────────────────────────────────────────────────────
    overlay_color = style_cfg.get("overlay_color", "#000000")
    overlay_opacity = style_cfg.get("overlay_opacity", 0.0)
    if overlay_opacity > 0:
        alpha = int(255 * overlay_opacity)
        r, g, b = hex_to_rgb(overlay_color)
        overlay = Image.new("RGBA", (width, height), (r, g, b, alpha))
        canvas = Image.alpha_composite(canvas, overlay)

    # ── 3. Header asset ──────────────────────────────────────────────────────
    hl = session.get("header_layer", {})
    if session.get("has_header") and hl.get("visible", True):
        paste_asset(
            canvas,
            session_dir / "assets" / "header.png",
            hl.get("x", 0), hl.get("y", 0),
            target_w=width,          # scale to canvas width, height follows ratio
            opacity=hl.get("opacity", 1.0),
        )

    # ── 4. Footer asset ──────────────────────────────────────────────────────
    fl = session.get("footer_layer", {})
    if session.get("has_footer") and fl.get("visible", True):
        paste_asset(
            canvas,
            session_dir / "assets" / "footer.png",
            fl.get("x", 0), fl.get("y", height - 160),
            target_w=width,          # scale to canvas width, height follows ratio
            opacity=fl.get("opacity", 1.0),
        )

    # ── 5. Logo asset ────────────────────────────────────────────────────────
    ll = session.get("logo_layer", {})
    if session.get("has_logo") and ll.get("visible", True):
        paste_asset(
            canvas,
            session_dir / "assets" / "logo.png",
            ll.get("x", 54), ll.get("y", 54),
            target_w=ll.get("width", 120), target_h=ll.get("height", 120),
            opacity=ll.get("opacity", 1.0),
        )

    # ── 6. Text layers ───────────────────────────────────────────────────────
    headline_layer = session.get("headline_layer", {})
    body_layer = session.get("body_layer", {})
    hashtag_layer = session.get("hashtag_layer", {})

    if headline_layer.get("visible", True) and headline_layer.get("text"):
        _hl_sz = headline_layer.get("font_size", 64)
        font = (_load_font(headline_layer["font_file"], _hl_sz)
                if headline_layer.get("font_file") else get_font(font_cfg, "headline", _hl_sz))
        draw_text_block(
            canvas,
            headline_layer["text"],
            center_x=headline_layer.get("x", width // 2),
            top_y=headline_layer.get("y", 280),
            font=font,
            color=headline_layer.get("color", "#FFFFFF"),
        )

    if body_layer.get("visible", True) and body_layer.get("text"):
        _body_sz = body_layer.get("font_size", 30)
        font = (_load_font(body_layer["font_file"], _body_sz)
                if body_layer.get("font_file") else get_font(font_cfg, "body", _body_sz))
        draw_text_block(
            canvas,
            body_layer["text"],
            center_x=body_layer.get("x", width // 2),
            top_y=body_layer.get("y", 520),
            font=font,
            color=body_layer.get("color", "#EEEEEE"),
        )

    # hashtags are shown in the editor copy panel, not painted on the image

    # ── 7. Save ──────────────────────────────────────────────────────────────
    out = canvas.convert("RGB")
    out_path = session_dir / "composed.png"
    out.save(str(out_path), "PNG", optimize=False)
    log.info("Composed image saved -> %s", out_path)
    return out_path
