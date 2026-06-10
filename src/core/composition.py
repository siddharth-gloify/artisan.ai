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
    align: str = "center",
) -> int:
    """Draw wrapped text. Returns the y after the last line.
    align='center': center_x is the horizontal midpoint of each line.
    align='left':   center_x is the left edge.
    """
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
        if align == "left":
            x = center_x
        else:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            x = center_x - text_w // 2
        draw.text((x, current_y), line, font=font, fill=fill)
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

    return Image.alpha_composite(canvas, overlay)


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
        canvas = Image.open(base_path).convert("RGBA")
        canvas = canvas.resize((width, height), Image.LANCZOS)
    else:
        bg_color     = palette.get("background", "#111111")
        gradient_end = palette.get("gradient_end", bg_color)
        canvas = create_gradient_background(width, height, bg_color, gradient_end).convert("RGBA")

    # ── 3. Overlay (driven entirely by edit_cfg) ──────────────────────────────
    overlay_type  = edit_cfg.get("overlay_type", "solid")
    overlay_color = edit_cfg.get("overlay_color", "#000000")

    if overlay_type in ("gradient_bottom", "gradient_top"):
        grad_op = edit_cfg.get("overlay_gradient_opacity", 0.72)
        canvas = draw_gradient_overlay(canvas, overlay_color, overlay_type, grad_op)
    elif overlay_type == "solid":
        ov_op = edit_cfg.get("overlay_opacity", 0.0)
        if ov_op > 0:
            alpha = int(255 * ov_op)
            r, g, b = hex_to_rgb(overlay_color)
            canvas = Image.alpha_composite(canvas, Image.new("RGBA", (width, height), (r, g, b, alpha)))
    # overlay_type == "none": no overlay applied

    # ── 4. Header / Footer assets ─────────────────────────────────────────────
    hl = session.get("header_layer", {})
    if session.get("has_header") and hl.get("visible", True):
        paste_asset(canvas, session_dir / "assets" / "header.png",
                    hl.get("x", 0), hl.get("y", 0), target_w=width, opacity=hl.get("opacity", 1.0))

    fl = session.get("footer_layer", {})
    if session.get("has_footer") and fl.get("visible", True):
        paste_asset(canvas, session_dir / "assets" / "footer.png",
                    fl.get("x", 0), fl.get("y", height - 160), target_w=width, opacity=fl.get("opacity", 1.0))

    # ── 5. Logo (position driven by edit_cfg.logo_pos) ───────────────────────
    ll = session.get("logo_layer", {})
    if session.get("has_logo") and ll.get("visible", True):
        logo_path = session_dir / "assets" / "logo.png"
        if logo_path.exists():
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
                max_w, max_h = edit_cfg.get("logo_max", [160, 100])
                scale    = min(max_w / logo_img.width, max_h / logo_img.height)
                logo_img = logo_img.resize(
                    (max(1, round(logo_img.width * scale)), max(1, round(logo_img.height * scale))),
                    Image.LANCZOS,
                )
                lw, lh = logo_img.size
                logo_pad = edit_cfg.get("logo_padding", 48)
                logo_pos = edit_cfg.get("logo_pos", "")

                if logo_pos == "top_right":
                    lx, ly = width - logo_pad - lw, logo_pad
                elif logo_pos == "top_left":
                    lx, ly = logo_pad, logo_pad
                else:   # legacy: honour session layer x/y
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

    # Contact bar height reservation for bottom zone
    cb = session.get("contact_bar_layer", {})
    bar_reserve = 80 if (cb.get("enabled") and cb.get("visible", True)) else 0

    # Compute headline anchor (y and x)
    if text_zone == "middle":
        # 35–60% band: text lives in the darker middle of cinematic images
        hl_y = int(height * 0.35)
        hl_x = side_pad if text_align == "left" else width // 2
    elif text_zone == "bottom":
        hl_y = int(height * 0.62)
        hl_x = side_pad if text_align == "left" else width // 2
    elif text_zone == "top":
        hl_y = 190  # below logo area
        hl_x = side_pad if text_align == "left" else width // 2
    elif text_zone == "center":
        hl_y = int(height * 0.38)
        hl_x = side_pad if text_align == "left" else width // 2
    else:  # legacy — use session layer coords directly
        hl_y       = headline_layer.get("y", 280)
        hl_x       = headline_layer.get("x", width // 2)
        text_align = "center"

    after_hl_y = hl_y
    max_text_w = width - side_pad * 2

    # Draw headline
    if headline_layer.get("visible", True) and headline_layer.get("text"):
        _hl_sz = headline_layer.get("font_size", 64)
        font = (_load_font(headline_layer["font_file"], _hl_sz)
                if headline_layer.get("font_file") else get_font(font_cfg, "headline", _hl_sz))
        after_hl_y = draw_text_block(
            canvas, headline_layer["text"],
            center_x=hl_x, top_y=hl_y, font=font,
            color=headline_layer.get("color", "#FFFFFF"),
            max_width=max_text_w,
            line_gap=hl_gap,
            align=text_align,
        )

    # Accent rule
    if do_rule and after_hl_y > hl_y:
        r_gap = edit_cfg.get("accent_gap_above", 18)
        r_len = edit_cfg.get("accent_rule_length", 200)
        r_thk = edit_cfg.get("accent_rule_thickness", 5)
        r_x   = side_pad if text_align == "left" else (width - r_len) // 2
        draw_accent_rule(canvas, r_x, after_hl_y + r_gap, r_len,
                         headline_layer.get("color", "#FFFFFF"), r_thk)
        body_start_y = after_hl_y + r_gap + r_thk + edit_cfg.get("accent_gap_below", 22)
    else:
        body_start_y = after_hl_y + 20

    # Body Y: legacy uses stored y; others flow below headline
    if text_zone == "legacy":
        body_y = body_layer.get("y", 520)
        bx     = body_layer.get("x", width // 2)
    else:
        body_y = body_start_y
        bx     = side_pad if text_align == "left" else width // 2

    # Draw body
    if body_layer.get("visible", True) and body_layer.get("text"):
        _body_sz = body_layer.get("font_size", 30)
        font = (_load_font(body_layer["font_file"], _body_sz)
                if body_layer.get("font_file") else get_font(font_cfg, "body", _body_sz))
        draw_text_block(
            canvas, body_layer["text"],
            center_x=bx, top_y=body_y, font=font,
            color=body_layer.get("color", "#EEEEEE"),
            max_width=max_text_w,
            line_gap=body_gap,
            align=text_align,
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
