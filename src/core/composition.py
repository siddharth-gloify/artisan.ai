"""Pillow composition engine — the heart of PostForge."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageEnhance

from src.utils.constants import (
    FONTS_DIR, WINDOWS_FONT_DIR, LINUX_FONT_DIRS,
    POST_WIDTH, POST_HEIGHT, TEXT_PADDING, MAX_TEXT_WIDTH,
)
from src.utils.helpers import hex_to_rgb, hex_to_rgba, clamp
from src.utils.logger import get_logger

log = get_logger(__name__)


def _resolve_color(value, palette: dict, default: str) -> str:
    """Resolve a config color value. Supports literal hex ('#FFAA00') and
    palette references ('palette.accent' → palette['accent'])."""
    if not value:
        return default
    if isinstance(value, str) and value.startswith("palette."):
        return palette.get(value.split(".", 1)[1], default)
    return value


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

def _line_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: int = 0) -> int:
    """Pixel width of a single line, accounting for letter-spacing (tracking)."""
    if tracking <= 0:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    total = 0.0
    for ch in text:
        total += draw.textlength(ch, font=font)
    return int(total + tracking * max(0, len(text) - 1))


def _draw_line(draw: ImageDraw.ImageDraw, x: float, y: float, line: str, font, fill, tracking: int = 0) -> None:
    """Draw one line of text, char-by-char when tracking is applied."""
    if tracking <= 0:
        draw.text((x, y), line, font=font, fill=fill)
        return
    cx = float(x)
    for ch in line:
        draw.text((cx, y), ch, font=font, fill=fill)
        cx += draw.textlength(ch, font=font) + tracking


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, tracking: int = 0) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        if _line_width(draw, test, font, tracking) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _line_height(draw: ImageDraw.ImageDraw, font) -> int:
    try:
        bbox_sample = draw.textbbox((0, 0), "Ag", font=font)
        return bbox_sample[3] - bbox_sample[1]
    except Exception:
        return font.size if hasattr(font, "size") else 20


def measure_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
    line_gap: int,
    tracking: int = 0,
    uppercase: bool = False,
) -> int:
    """Height (px) a draw_text_block call will consume, without the trailing gap."""
    if not text or not text.strip():
        return 0
    if uppercase:
        text = text.upper()
    lines = _wrap_text(draw, text, font, max_width, tracking)
    if not lines:
        return 0
    lh = _line_height(draw, font)
    return len(lines) * (lh + line_gap) - line_gap


def draw_text_block(
    canvas: Image.Image,
    text: str,
    center_x: int,
    top_y: int,
    font,
    color: str,
    max_width: int = MAX_TEXT_WIDTH,
    line_gap: int = 10,
    align: str = "center",
    tracking: int = 0,
    uppercase: bool = False,
    shadow: bool = False,
) -> int:
    """Draw wrapped text. Returns the y after the last line.
    align='center': center_x is the horizontal midpoint of each line.
    align='left':   center_x is the left edge.
    tracking: extra px between characters (premium editorial look).
    shadow: soft offset shadow under each line for legibility on photos.
    """
    if not text.strip():
        return top_y
    if uppercase:
        text = text.upper()

    draw = ImageDraw.Draw(canvas, "RGBA")
    lines = _wrap_text(draw, text, font, max_width, tracking)
    if not lines:
        return top_y

    line_height = _line_height(draw, font)

    r, g, b = hex_to_rgb(color)
    fill = (r, g, b, 255)

    current_y = top_y
    for line in lines:
        if align == "left":
            x = center_x
        else:
            x = center_x - _line_width(draw, line, font, tracking) // 2
        if shadow:
            _draw_line(draw, x + 2, current_y + 4, line, font, (0, 0, 0, 120), tracking)
        _draw_line(draw, x, current_y, line, font, fill, tracking)
        current_y += line_height + line_gap

    return current_y


# ---------------------------------------------------------------------------
# Directional gradient overlay
# ---------------------------------------------------------------------------

def draw_gradient_overlay(
    canvas: Image.Image,
    color: str,
    direction: str,
    max_opacity: float,
) -> Image.Image:
    """Composite a directional gradient over canvas and return the composited result.
    direction='gradient_bottom': transparent at top, opaque at bottom edge.
    direction='gradient_top':    opaque at top, transparent toward the middle.
    """
    width, height = canvas.size
    r, g, b = hex_to_rgb(color)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if direction == "gradient_bottom":
        fade_start = int(height * 0.40)
        for y in range(height):
            if y <= fade_start:
                alpha = 0
            else:
                t = (y - fade_start) / (height - fade_start)
                alpha = int(max_opacity * 255 * min(1.0, t ** 0.75))
            draw.line([(0, y), (width, y)], fill=(r, g, b, alpha))
    elif direction == "gradient_top":
        fade_end = int(height * 0.50)
        for y in range(height):
            if y >= fade_end:
                alpha = 0
            else:
                t = 1.0 - (y / fade_end)
                alpha = int(max_opacity * 255 * min(1.0, t ** 0.75))
            draw.line([(0, y), (width, y)], fill=(r, g, b, alpha))
    elif direction == "gradient_left":
        fade_end = int(width * 0.72)
        for x in range(width):
            if x >= fade_end:
                alpha = 0
            else:
                t = 1.0 - (x / fade_end)
                alpha = int(max_opacity * 255 * min(1.0, t ** 0.8))
            draw.line([(x, 0), (x, height)], fill=(r, g, b, alpha))

    return Image.alpha_composite(canvas, overlay)


# ---------------------------------------------------------------------------
# Premium design primitives — vignette, duotone, frame, band, backdrop, kicker
# ---------------------------------------------------------------------------

def draw_vignette(canvas: Image.Image, strength: float = 0.55, color: str = "#000000") -> Image.Image:
    """Darken edges/corners like a photo-editor vignette. Center stays clean."""
    w, h = canvas.size
    sw, sh = max(2, w // 8), max(2, h // 8)
    mask = Image.new("L", (sw, sh), int(255 * strength))
    md = ImageDraw.Draw(mask)
    md.ellipse([int(sw * 0.06), int(sh * 0.06), int(sw * 0.94), int(sh * 0.94)], fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(max(4, sw // 5)))
    mask = mask.resize((w, h), Image.BILINEAR)
    r, g, b = hex_to_rgb(color)
    overlay = Image.new("RGBA", (w, h), (r, g, b, 255))
    overlay.putalpha(mask)
    return Image.alpha_composite(canvas, overlay)


def apply_duotone(img: Image.Image, dark_hex: str, light_hex: str) -> Image.Image:
    """Map photo tones onto two brand colors — classic campaign treatment."""
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=2)
    duo = ImageOps.colorize(gray, black=hex_to_rgb(dark_hex), white=hex_to_rgb(light_hex))
    return duo.convert("RGBA")


def apply_mute(img: Image.Image) -> Image.Image:
    """Slightly desaturate + darken — makes overlaid type feel intentional."""
    out = ImageEnhance.Color(img.convert("RGB")).enhance(0.72)
    out = ImageEnhance.Brightness(out).enhance(0.88)
    return out.convert("RGBA")


def draw_frame(canvas: Image.Image, inset: int, thickness: int, color: str) -> None:
    """Thin inner border — gallery / editorial framing device."""
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    r, g, b = hex_to_rgb(color)
    for i in range(thickness):
        draw.rectangle([inset + i, inset + i, w - 1 - inset - i, h - 1 - inset - i],
                       outline=(r, g, b, 255))


def draw_bottom_band(canvas: Image.Image, frac: float, color: str, opacity: float = 1.0) -> int:
    """Solid color block covering the bottom `frac` of the canvas. Returns band top y."""
    w, h = canvas.size
    band_top = int(h * (1.0 - frac))
    draw = ImageDraw.Draw(canvas, "RGBA")
    r, g, b = hex_to_rgb(color)
    draw.rectangle([0, band_top, w, h], fill=(r, g, b, int(255 * opacity)))
    return band_top


def draw_text_backdrop(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    kind: str,
    color: str,
    opacity: float,
    radius: int = 28,
) -> None:
    """Panel behind the text stack. kind='card' (solid) or 'glass' (blur + tint)."""
    w, h = canvas.size
    x0 = max(0, box[0]); y0 = max(0, box[1])
    x1 = min(w - 1, box[2]); y1 = min(h - 1, box[3])
    if x1 <= x0 or y1 <= y0:
        return
    if kind == "glass":
        region = canvas.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(16))
        mask = Image.new("L", region.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, region.width - 1, region.height - 1], radius=radius, fill=255)
        canvas.paste(region, (x0, y0), mask)
    draw = ImageDraw.Draw(canvas, "RGBA")
    r, g, b = hex_to_rgb(color)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=(r, g, b, int(255 * opacity)))


def draw_kicker(
    canvas: Image.Image,
    text: str,
    x: int,
    y: int,
    align: str,
    width_mid: int,
    style: str,
    font,
    accent_color: str,
    text_color: str = "#FFFFFF",
) -> int:
    """Small eyebrow label above the headline ('NEW ARRIVAL', 'CASE STUDY' ...).
    style='pill' → rounded accent chip; style='tracked' → spaced uppercase text.
    Returns total height consumed including the gap below."""
    text = text.upper().strip()
    if not text:
        return 0
    draw = ImageDraw.Draw(canvas, "RGBA")
    tracking = 4
    tw = _line_width(draw, text, font, tracking)
    bbox = draw.textbbox((0, 0), text, font=font)
    th = bbox[3] - bbox[1]

    if style == "pill":
        pad_x, pad_y = 24, 13
        pill_w, pill_h = tw + pad_x * 2, th + pad_y * 2
        px = x if align == "left" else width_mid - pill_w // 2
        ar, ag, ab = hex_to_rgb(accent_color)
        draw.rounded_rectangle([px, y, px + pill_w, y + pill_h],
                               radius=pill_h // 2, fill=(ar, ag, ab, 255))
        tr, tg, tb = hex_to_rgb(text_color)
        _draw_line(draw, px + pad_x, y + pad_y - bbox[1], text, font, (tr, tg, tb, 255), tracking)
        return pill_h + 28

    # tracked text style
    tx = x if align == "left" else width_mid - tw // 2
    ar, ag, ab = hex_to_rgb(accent_color)
    _draw_line(draw, tx, y - bbox[1], text, font, (ar, ag, ab, 255), tracking)
    return th + 24


def measure_kicker(draw: ImageDraw.ImageDraw, text: str, style: str, font) -> int:
    text = text.upper().strip()
    if not text:
        return 0
    bbox = draw.textbbox((0, 0), text, font=font)
    th = bbox[3] - bbox[1]
    return (th + 26 + 28) if style == "pill" else (th + 24)


def draw_quote_mark(
    canvas: Image.Image,
    x: int,
    y: int,
    align: str,
    width_mid: int,
    font_cfg: dict,
    color: str,
    size: int = 150,
) -> int:
    """Large decorative opening quote above the headline. Returns height consumed."""
    font = get_font(font_cfg, "headline", size)
    draw = ImageDraw.Draw(canvas, "RGBA")
    glyph = "“"
    bbox = draw.textbbox((0, 0), glyph, font=font)
    gw = bbox[2] - bbox[0]
    gh = bbox[3] - bbox[1]
    gx = x if align == "left" else width_mid - gw // 2
    r, g, b = hex_to_rgb(color)
    draw.text((gx - bbox[0], y - bbox[1]), glyph, font=font, fill=(r, g, b, 255))
    return gh + 16


def measure_quote_mark(draw: ImageDraw.ImageDraw, font_cfg: dict, size: int = 150) -> int:
    font = get_font(font_cfg, "headline", size)
    bbox = draw.textbbox((0, 0), "“", font=font)
    return (bbox[3] - bbox[1]) + 16


# ---------------------------------------------------------------------------
# Accent rule line
# ---------------------------------------------------------------------------

def draw_accent_rule(
    canvas: Image.Image,
    x: int,
    y: int,
    length: int,
    color: str,
    thickness: int = 4,
) -> None:
    """Draw a thin horizontal rule between headline and body text."""
    draw = ImageDraw.Draw(canvas)
    r, g, b = hex_to_rgb(color)
    draw.rectangle([x, y, x + length, y + thickness], fill=(r, g, b, 255))


# ---------------------------------------------------------------------------
# Contact / branding bar
# ---------------------------------------------------------------------------

def draw_contact_bar(
    canvas: Image.Image,
    width: int,
    height: int,
    phone: str,
    email: str,
    bg_color: str,
    text_color: str,
    font_cfg: dict,
    bar_height: int = 80,
) -> None:
    """Draw a branded contact-info bar at the very bottom of the canvas."""
    r, g, b = hex_to_rgb(bg_color)
    bar_y = height - bar_height
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, bar_y, width, height], fill=(r, g, b, 255))

    font = get_font(font_cfg, "body", 26)
    tr, tg, tb = hex_to_rgb(text_color)
    fill = (tr, tg, tb, 255)

    try:
        th = draw.textbbox((0, 0), "Ag", font=font)
        text_h = th[3] - th[1]
    except Exception:
        text_h = 26
    text_y = bar_y + (bar_height - text_h) // 2

    pad = 44
    if phone:
        draw.text((pad, text_y), f"☎  {phone}", font=font, fill=fill)
    if email:
        email_str = f"✉  {email}"
        try:
            ew = draw.textbbox((0, 0), email_str, font=font)[2]
        except Exception:
            ew = len(email_str) * 14
        draw.text((width - pad - ew, text_y), email_str, font=font, fill=fill)


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
    """Full composition pipeline. Returns path to the saved composed.png."""

    # ── Resolve edit style config ────────────────────────────────────────────
    # New sessions store edit_style; legacy sessions fall back to image_style
    edit_id  = session.get("edit_style") or session.get("image_style", "")
    edit_cfg = (config.get("edit_styles", {}).get(edit_id) or
                config.get("image_styles", {}).get(edit_id, {}))

    palette  = config["color_palettes"].get(session["palette_id"], {})
    font_cfg = config["font_styles"].get(session["font_style"], {})

    width, height = POST_WIDTH, POST_HEIGHT
    base_path = session_dir / "base_image.png"

    # ── 1. Route split layouts to their own path ─────────────────────────────
    if edit_cfg.get("layout") == "split":
        canvas = _compose_split_layout(
            session, edit_cfg, palette, font_cfg,
            base_path, session_dir, width, height,
        )
        out_path = session_dir / "composed.png"
        canvas.convert("RGB").save(str(out_path), "PNG", optimize=False)
        log.info("Composed image saved -> %s", out_path)
        return out_path

    # ── 2. Base image (or palette gradient fallback) ──────────────────────────
    if base_path.exists():
        photo = Image.open(base_path).convert("RGBA")
    else:
        bg_color     = palette.get("background", "#111111")
        gradient_end = palette.get("gradient_end", bg_color)
        photo = create_gradient_background(width, height, bg_color, gradient_end).convert("RGBA")

    # Optional photo treatment (duotone / mute) — applied to the photo itself
    treatment = edit_cfg.get("photo_treatment", "none")
    if treatment == "duotone":
        duo_dark  = _resolve_color(edit_cfg.get("duotone_dark", "palette.background"), palette, "#101020")
        duo_light = _resolve_color(edit_cfg.get("duotone_light", "palette.primary"), palette, "#E8E0D0")
        photo = apply_duotone(photo, duo_dark, duo_light)
    elif treatment == "mute":
        photo = apply_mute(photo)

    matte_bottom = edit_cfg.get("matte_bottom", 330)
    if edit_cfg.get("photo_matte"):
        # Print/studio look: photo inset on a solid matte with a soft drop shadow
        matte_pad   = edit_cfg.get("matte_padding", 64)
        matte_color = _resolve_color(edit_cfg.get("matte_color", "palette.background"), palette, "#F5F0EB")
        mr, mg, mb  = hex_to_rgb(matte_color)
        canvas = Image.new("RGBA", (width, height), (mr, mg, mb, 255))

        ph_box = (matte_pad, matte_pad, width - matte_pad, height - matte_bottom)
        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle(
            [ph_box[0] + 8, ph_box[1] + 14, ph_box[2] + 8, ph_box[3] + 14], fill=(0, 0, 0, 80))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        canvas = Image.alpha_composite(canvas, shadow)

        bw, bh = ph_box[2] - ph_box[0], ph_box[3] - ph_box[1]
        scale = max(bw / photo.width, bh / photo.height)
        photo = photo.resize((max(1, round(photo.width * scale)), max(1, round(photo.height * scale))), Image.LANCZOS)
        left = (photo.width - bw) // 2
        top  = (photo.height - bh) // 2
        canvas.paste(photo.crop((left, top, left + bw, top + bh)), (ph_box[0], ph_box[1]))
    else:
        canvas = photo.resize((width, height), Image.LANCZOS)

    # ── 3. Overlay (driven entirely by edit_cfg) ──────────────────────────────
    overlay_type  = edit_cfg.get("overlay_type", "solid")
    overlay_color = edit_cfg.get("overlay_color", "#000000")

    if overlay_type in ("gradient_bottom", "gradient_top", "gradient_left"):
        grad_op = edit_cfg.get("overlay_gradient_opacity", 0.72)
        canvas = draw_gradient_overlay(canvas, overlay_color, overlay_type, grad_op)
    elif overlay_type == "vignette":
        canvas = draw_vignette(canvas, edit_cfg.get("overlay_opacity", 0.55), overlay_color)
    elif overlay_type == "solid":
        ov_op = edit_cfg.get("overlay_opacity", 0.0)
        if ov_op > 0:
            alpha = int(255 * ov_op)
            r, g, b = hex_to_rgb(overlay_color)
            canvas = Image.alpha_composite(canvas, Image.new("RGBA", (width, height), (r, g, b, alpha)))
    # overlay_type == "none": no overlay applied

    # Solid color band across the bottom (agency statement-band layout)
    band_frac = edit_cfg.get("bottom_band_frac", 0)
    band_top  = None
    if band_frac:
        band_color = _resolve_color(edit_cfg.get("bottom_band_color", "palette.primary"), palette, "#1A3A5C")
        band_top = draw_bottom_band(canvas, band_frac, band_color,
                                    edit_cfg.get("bottom_band_opacity", 1.0))

    # Thin inner frame (gallery / editorial device)
    if edit_cfg.get("frame"):
        frame_color = _resolve_color(edit_cfg.get("frame_color", "#FFFFFF"), palette, "#FFFFFF")
        draw_frame(canvas, edit_cfg.get("frame_inset", 36),
                   edit_cfg.get("frame_thickness", 3), frame_color)

    # ── 4. Header / Footer assets ─────────────────────────────────────────────
    hl = session.get("header_layer", {})
    if session.get("has_header") and hl.get("visible", True):
        paste_asset(canvas, session_dir / "assets" / "header.png",
                    hl.get("x", 0), hl.get("y", 0),
                    target_w=hl.get("width", width), target_h=hl.get("height") or None,
                    opacity=hl.get("opacity", 1.0))

    fl = session.get("footer_layer", {})
    if session.get("has_footer") and fl.get("visible", True):
        paste_asset(canvas, session_dir / "assets" / "footer.png",
                    fl.get("x", 0), fl.get("y", height - 160),
                    target_w=fl.get("width", width), target_h=fl.get("height") or None,
                    opacity=fl.get("opacity", 1.0))

    # ── 5. Logo (position driven by edit_cfg.logo_pos) ───────────────────────
    ll = session.get("logo_layer", {})
    if session.get("has_logo") and ll.get("visible", True):
        logo_path = session_dir / "assets" / "logo.png"
        if logo_path.exists():
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
                default_max = edit_cfg.get("logo_max", [160, 100])
                max_w = ll.get("width") or default_max[0]
                max_h = ll.get("height") or default_max[1]
                scale    = min(max_w / logo_img.width, max_h / logo_img.height)
                logo_img = logo_img.resize(
                    (max(1, round(logo_img.width * scale)), max(1, round(logo_img.height * scale))),
                    Image.LANCZOS,
                )
                lw, lh = logo_img.size
                logo_pad = edit_cfg.get("logo_padding", 48)
                logo_pos = edit_cfg.get("logo_pos", "")

                if ll.get("position_override"):
                    lx, ly = ll.get("x", 54), ll.get("y", 54)
                elif logo_pos == "top_right":
                    lx, ly = width - logo_pad - lw, logo_pad
                elif logo_pos == "top_left":
                    lx, ly = logo_pad, logo_pad
                else:
                    lx, ly = ll.get("x", 54), ll.get("y", 54)

                if ll.get("opacity", 1.0) < 1.0:
                    r, g, b, a = logo_img.split()
                    a = a.point(lambda p: int(p * ll.get("opacity", 1.0)))
                    logo_img.putalpha(a)
                canvas.paste(logo_img, (lx, ly), logo_img)
            except Exception as exc:
                log.warning("Logo paste error: %s", exc)

    # ── 6. Text layers ────────────────────────────────────────────────────────
    headline_layer = session.get("headline_layer", {})
    body_layer     = session.get("body_layer", {})

    # Layout parameters from edit_cfg
    text_zone  = edit_cfg.get("text_zone", "legacy")
    text_align = edit_cfg.get("text_align", "center")
    hl_gap     = edit_cfg.get("headline_line_gap", 8)
    body_gap   = edit_cfg.get("body_line_gap", 12)
    side_pad   = edit_cfg.get("side_padding", TEXT_PADDING)
    do_rule    = edit_cfg.get("accent_rule", False)

    # Premium typography options
    hl_upper   = edit_cfg.get("headline_transform", "") == "uppercase"
    hl_track   = edit_cfg.get("headline_tracking", 0)
    txt_shadow = edit_cfg.get("text_shadow", False)

    # Contact bar height reservation for bottom zone
    cb = session.get("contact_bar_layer", {})
    bar_reserve = 80 if (cb.get("enabled") and cb.get("visible", True)) else 0

    max_text_w   = width - side_pad * 2
    measure_draw = ImageDraw.Draw(canvas, "RGBA")

    # Resolve fonts up-front — needed to measure the stack before drawing
    _hl_sz  = headline_layer.get("font_size", 64)
    hl_font = (_load_font(headline_layer["font_file"], _hl_sz)
               if headline_layer.get("font_file") else get_font(font_cfg, "headline", _hl_sz))
    _body_sz  = body_layer.get("font_size", 30)
    body_font = (_load_font(body_layer["font_file"], _body_sz)
                 if body_layer.get("font_file") else get_font(font_cfg, "body", _body_sz))

    # Kicker (eyebrow label above the headline) — reuses tag_layer text + colors
    kicker_style = edit_cfg.get("kicker_style", "none")
    tag_layer    = session.get("tag_layer", {})
    kicker_text  = ""
    if kicker_style in ("pill", "tracked") and tag_layer.get("visible", True):
        kicker_text = str(tag_layer.get("text", "")).strip()
    kicker_font = get_font(font_cfg, "body", tag_layer.get("font_size", 24))

    # Measure the full text stack (drives backdrops, side bars, vertical centering)
    hl_visible   = bool(headline_layer.get("visible", True) and headline_layer.get("text"))
    body_visible = bool(body_layer.get("visible", True) and body_layer.get("text"))

    quote_h  = (measure_quote_mark(measure_draw, font_cfg, edit_cfg.get("quote_size", 150))
                if edit_cfg.get("quote_mark") else 0)
    kicker_h = measure_kicker(measure_draw, kicker_text, kicker_style, kicker_font) if kicker_text else 0
    hl_h     = (measure_text_block(measure_draw, headline_layer.get("text", ""), hl_font,
                                   max_text_w, hl_gap, hl_track, hl_upper) if hl_visible else 0)
    body_h   = (measure_text_block(measure_draw, body_layer.get("text", ""), body_font,
                                   max_text_w, body_gap) if body_visible else 0)

    rule_extra = 0
    if do_rule and hl_h:
        rule_extra = (edit_cfg.get("accent_gap_above", 18) +
                      edit_cfg.get("accent_rule_thickness", 5) +
                      edit_cfg.get("accent_gap_below", 22))

    total_h = quote_h + kicker_h + hl_h
    if hl_h and body_h:
        total_h += hl_gap + (rule_extra if rule_extra else 20)
    total_h += body_h

    # Compute stack anchor (top of quote/kicker/headline stack)
    hl_dx = headline_layer.get("x_offset", 0)
    hl_dy = headline_layer.get("y_offset", 0)
    hl_x  = (side_pad if text_align == "left" else width // 2) + hl_dx
    if text_zone == "middle":
        # 35–60% band: text lives in the darker middle of cinematic images
        stack_y = int(height * 0.35) + hl_dy
    elif text_zone == "bottom":
        stack_y = int(height * 0.62) + hl_dy
    elif text_zone == "top":
        stack_y = 190 + hl_dy  # below logo area
    elif text_zone == "center":
        stack_y = int(height * 0.38) + hl_dy
    elif text_zone == "center_stack":
        # True vertical centering of the measured stack (premium centered layouts)
        stack_y = max(140, (height - bar_reserve - total_h) // 2) + hl_dy
    elif text_zone == "band" and band_top is not None:
        stack_y = band_top + edit_cfg.get("band_text_pad", 56) + hl_dy
    elif text_zone == "matte":
        stack_y = height - matte_bottom + edit_cfg.get("matte_text_pad", 48) + hl_dy
    else:  # legacy — use session layer coords directly
        stack_y    = headline_layer.get("y", 280)
        hl_x       = headline_layer.get("x", width // 2)
        text_align = "center"

    # Backdrop panel behind the text stack (card / glass)
    backdrop = edit_cfg.get("text_backdrop", "none")
    if backdrop in ("card", "glass") and total_h > 0 and text_zone != "legacy":
        bd_pad_x = edit_cfg.get("backdrop_pad_x", 48)
        bd_pad_y = edit_cfg.get("backdrop_pad_y", 44)
        bd_color = _resolve_color(
            edit_cfg.get("backdrop_color", "#FFFFFF" if backdrop == "card" else "#10131A"),
            palette, "#FFFFFF")
        bd_op = edit_cfg.get("backdrop_opacity", 0.96 if backdrop == "card" else 0.45)
        draw_text_backdrop(
            canvas,
            (side_pad - bd_pad_x, stack_y - bd_pad_y,
             width - side_pad + bd_pad_x, stack_y + total_h + bd_pad_y),
            backdrop, bd_color, bd_op,
            radius=edit_cfg.get("backdrop_radius", 28),
        )

    # Vertical accent bar alongside left-aligned text
    if edit_cfg.get("side_bar") and total_h > 0 and text_align == "left" and text_zone != "legacy":
        bar_w     = edit_cfg.get("side_bar_width", 10)
        bar_color = _resolve_color(edit_cfg.get("side_bar_color", "palette.accent"), palette, "#FFFFFF")
        sbx = hl_x - edit_cfg.get("side_bar_gap", 30) - bar_w
        br, bg_, bb = hex_to_rgb(bar_color)
        ImageDraw.Draw(canvas, "RGBA").rectangle(
            [sbx, stack_y, sbx + bar_w, stack_y + total_h], fill=(br, bg_, bb, 255))

    # Draw the stack: quote mark → kicker → headline → rule → body
    cur_y = stack_y
    if edit_cfg.get("quote_mark"):
        q_color = _resolve_color(edit_cfg.get("quote_color", "palette.accent"), palette, "#FFFFFF")
        cur_y += draw_quote_mark(canvas, hl_x, cur_y, text_align, hl_x,
                                 font_cfg, q_color, edit_cfg.get("quote_size", 150))
    if kicker_text:
        k_accent = tag_layer.get("bg_color", palette.get("accent", "#B48C3C"))
        k_text_c = tag_layer.get("text_color", "#FFFFFF")
        if kicker_style == "tracked":
            k_accent = _resolve_color(edit_cfg.get("kicker_color", "palette.accent"), palette, k_accent)
        cur_y += draw_kicker(canvas, kicker_text, hl_x, cur_y, text_align, hl_x,
                             kicker_style, kicker_font, k_accent, k_text_c)

    # Draw headline
    after_hl_y = cur_y
    if hl_visible:
        after_hl_y = draw_text_block(
            canvas, headline_layer["text"],
            center_x=hl_x, top_y=cur_y, font=hl_font,
            color=headline_layer.get("color", "#FFFFFF"),
            max_width=max_text_w,
            line_gap=hl_gap,
            align=text_align,
            tracking=hl_track,
            uppercase=hl_upper,
            shadow=txt_shadow,
        )

    # Accent rule
    if do_rule and after_hl_y > cur_y:
        r_gap = edit_cfg.get("accent_gap_above", 18)
        r_len = edit_cfg.get("accent_rule_length", 200)
        r_thk = edit_cfg.get("accent_rule_thickness", 5)
        r_x   = side_pad if text_align == "left" else (width - r_len) // 2
        rule_color = _resolve_color(edit_cfg.get("accent_rule_color", ""),
                                    palette, headline_layer.get("color", "#FFFFFF"))
        draw_accent_rule(canvas, r_x, after_hl_y + r_gap, r_len, rule_color, r_thk)
        body_start_y = after_hl_y + r_gap + r_thk + edit_cfg.get("accent_gap_below", 22)
    else:
        body_start_y = after_hl_y + 20

    # Body Y: legacy uses stored y; others flow below headline
    body_dx = body_layer.get("x_offset", 0)
    body_dy = body_layer.get("y_offset", 0)
    if text_zone == "legacy":
        body_y = body_layer.get("y", 520)
        bx     = body_layer.get("x", width // 2)
    else:
        body_y = body_start_y + body_dy
        bx     = (side_pad if text_align == "left" else width // 2) + body_dx

    # Draw body
    if body_visible:
        draw_text_block(
            canvas, body_layer["text"],
            center_x=bx, top_y=body_y, font=body_font,
            color=body_layer.get("color", "#EEEEEE"),
            max_width=max_text_w,
            line_gap=body_gap,
            align=text_align,
            shadow=txt_shadow,
        )

    # hashtags shown in editor copy panel only — not painted

    # ── 7. Contact bar ────────────────────────────────────────────────────────
    if cb.get("enabled") and cb.get("visible", True):
        draw_contact_bar(
            canvas, width, height,
            cb.get("phone", ""), cb.get("email", ""),
            cb.get("bg_color", "#1a2e55"), cb.get("text_color", "#FFFFFF"),
            font_cfg,
        )

    # ── 8. Save ───────────────────────────────────────────────────────────────
    out_path = session_dir / "composed.png"
    canvas.convert("RGB").save(str(out_path), "PNG", optimize=False)
    log.info("Composed image saved -> %s", out_path)
    return out_path
