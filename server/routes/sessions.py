"""Main session flow: home page → generate → editor."""

import io
import shutil
import time
from typing import Optional

from fastapi import APIRouter, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from PIL import Image

from src.core import session_manager as sm
from src.core.composition import compose_post
from src.core.image_processor import generate_base_image
from src.core.prompt_formatter import (
    build_caption_prompt, build_image_prompt, build_social_prompt, build_brand_analysis_prompt,
)
from src.core.text_generator import generate_caption, generate_social, generate_brand_config
from src.utils.constants import SESSIONS_DIR, OUTPUT_DIR, POST_WIDTH
from src.utils.helpers import ensure_dir, sanitize_filename
from src.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter()


# ── Home ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    cfg = request.app.state.config
    templates = request.app.state.templates
    return templates.TemplateResponse("index.html", {
        "request": request,
        "industries": cfg["industries"],
        "image_types": cfg.get("image_types", {}),
        "image_type_categories": cfg.get("image_type_categories", {}),
        "edit_styles": cfg.get("edit_styles", {}),
        "edit_style_categories": cfg.get("edit_style_categories", {}),
        "image_styles": cfg["image_styles"],          # legacy
        "style_categories": cfg["style_categories"],  # legacy
        "caption_tones": cfg["caption_tones"],
        "palettes": cfg["color_palettes"],
        "palette_categories": cfg["palette_categories"],
        "font_styles": cfg["font_styles"],
        "quick_starts": cfg["quick_start_templates"],
    })


# ── Generate ─────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate(
    request: Request,
    industry: str = Form(""),            # optional — auto-filled from brand description
    image_type: str = Form(""),          # optional — auto-filled from brand description
    edit_style: str = Form(""),
    image_style: str = Form(""),         # legacy compat
    caption_tone: str = Form(...),
    palette_id: str = Form(""),          # optional — auto-filled from brand description
    font_style: str = Form(...),
    topic: str = Form(...),
    image_tier: str = Form("normal"),
    brand_description: str = Form(""),
    contact_phone: str = Form(""),
    contact_email: str = Form(""),
    logo_file: Optional[UploadFile] = File(None),
    header_file: Optional[UploadFile] = File(None),
    footer_file: Optional[UploadFile] = File(None),
    bg_file: Optional[UploadFile] = File(None),
):
    cfg = request.app.state.config
    ensure_dir(SESSIONS_DIR)

    # Resolve IDs — new form sends image_type + edit_style; legacy sends image_style
    resolved_image_type = image_type or image_style
    resolved_edit_style = edit_style or image_style

    # Auto-fill optional fields (industry, image_type, palette_id) when left blank
    needs_fill = not industry or not resolved_image_type or not palette_id
    if needs_fill:
        _defaults = {
            "industry":   "lifestyle",
            "image_type": "photo_lifestyle",
            "edit_style": resolved_edit_style,
            "caption_tone": caption_tone,
            "palette_id": "neutral_elegant",
            "font_style": font_style,
        }
        if brand_description.strip():
            _prompt = build_brand_analysis_prompt(
                brand_description.strip(), topic,
                industries    = list(cfg["industries"].keys()),
                image_types   = list(cfg.get("image_types", {}).keys()),
                edit_styles   = list(cfg.get("edit_styles", {}).keys()),
                caption_tones = list(cfg["caption_tones"].keys()),
                palettes      = list(cfg["color_palettes"].keys()),
                font_styles   = list(cfg["font_styles"].keys()),
            )
            _filled = generate_brand_config(_prompt, _defaults)
            _valid = {
                "industry":   list(cfg["industries"].keys()),
                "image_type": list(cfg.get("image_types", {}).keys()),
                "palette_id": list(cfg["color_palettes"].keys()),
            }
            for k, v in _valid.items():
                _filled[k] = _filled.get(k) if _filled.get(k) in v else _defaults[k]
        else:
            _filled = _defaults

        if not industry:            industry            = _filled["industry"]
        if not resolved_image_type: resolved_image_type = _filled["image_type"]
        if not palette_id:          palette_id          = _filled["palette_id"]

    # 1. Create session
    session = sm.create_session(
        industry=industry,
        image_style=image_style or edit_style,   # legacy compat
        caption_tone=caption_tone,
        palette_id=palette_id,
        font_style=font_style,
        topic=topic,
        image_tier=image_tier,
        image_type=resolved_image_type,
        edit_style=resolved_edit_style,
    )
    sid = session["session_id"]
    session_dir = SESSIONS_DIR / sid

    # Apply edit_style defaults: font sizes and text color mode
    edit_cfg = cfg.get("edit_styles", {}).get(resolved_edit_style, {})
    palette  = cfg["color_palettes"].get(palette_id, {})

    if edit_cfg.get("headline_default_size"):
        session["headline_layer"]["font_size"] = edit_cfg["headline_default_size"]
    if edit_cfg.get("body_default_size"):
        session["body_layer"]["font_size"] = edit_cfg["body_default_size"]

    # Text colors: dark mode for editorial styles, white for cinematic/drama,
    # white_pure for text on brand-colored surfaces (bands, duotones)
    text_color_mode = edit_cfg.get("text_color_mode", "white")
    if text_color_mode == "dark":
        session["headline_layer"]["color"] = palette.get("primary", "#1a2e55")
        session["body_layer"]["color"]     = palette.get("secondary", "#4A5568")
    elif text_color_mode == "white_pure":
        session["headline_layer"]["color"] = "#FFFFFF"
        session["body_layer"]["color"]     = "#F2F2F2"
    else:
        session["headline_layer"]["color"] = palette.get("text_primary", "#FFFFFF")
        session["body_layer"]["color"]     = palette.get("text_secondary", "#CCCCCC")

    # Initialize logo position to match the edit style's preset so d-pad starts from correct spot
    _sync_logo_position(session, edit_cfg)

    # Store brand description
    session["brand_description"] = brand_description.strip()

    # Auto-enable contact bar if this edit style recommends it and phone/email provided
    if contact_phone or contact_email:
        session["contact_bar_layer"]["phone"]   = contact_phone
        session["contact_bar_layer"]["email"]   = contact_email
        session["contact_bar_layer"]["enabled"] = True
    elif edit_cfg.get("contact_bar_default"):
        session["contact_bar_layer"]["enabled"] = False  # off until user enters details

    # Save any pre-uploaded assets from the index page form
    _presave_asset(logo_file,   session, session_dir, "logo")
    _presave_asset(header_file, session, session_dir, "header")
    _presave_asset(footer_file, session, session_dir, "footer")
    _presave_asset(bg_file,     session, session_dir, "background")

    try:
        # Resolve image type config for AI prompt generation
        image_type_cfg = (cfg.get("image_types", {}).get(resolved_image_type) or
                          cfg.get("image_styles", {}).get(resolved_image_type, {}))

        # 2. Generate caption
        tone_cfg = cfg["caption_tones"].get(caption_tone, {})
        fallback = cfg.get("fallback_caption", {
            "headline": "Make it happen",
            "body": "Your story starts here.",
            "hashtags": ["#PostForge"],
        })
        caption_prompt = build_caption_prompt(topic, tone_cfg, industry,
                                             brand_context=session.get("brand_description", ""))
        caption = generate_caption(caption_prompt, fallback)
        session["caption"] = caption
        session["social_caption"] = caption.get("social_caption", "")

        # 3. Sync text layers with generated caption (color already set above)
        session["headline_layer"]["text"] = caption["headline"]
        session["body_layer"]["text"]     = caption["body"]
        session["hashtag_layer"]["text"]  = " ".join(caption["hashtags"])

        # Tag pill for split layouts + kicker label for premium layouts
        if edit_cfg.get("layout") == "split" or edit_cfg.get("kicker_style") in ("pill", "tracked"):
            hashtags  = caption.get("hashtags", [])
            first_tag = hashtags[0].lstrip("#") if hashtags else " ".join(topic.split()[:3])
            session["tag_layer"]["text"]       = first_tag.upper()
            session["tag_layer"]["bg_color"]   = palette.get("accent", "#B48C3C")
            session["tag_layer"]["text_color"] = palette.get("text_primary", "#FFFFFF")

        # 4. Generate base image using image_type_cfg (+ layout copy-space hints)
        img_prompt = build_image_prompt(topic, image_type_cfg, palette,
                                        industry=industry, edit_cfg=edit_cfg)
        base_path  = session_dir / "base_image.png"
        await generate_base_image(img_prompt, palette, base_path, tier=image_tier)

        # 5. Compose final image
        compose_post(session, cfg, session_dir)

        session["status"] = "ready"
        _save_to_output(session)

    except Exception as exc:
        log.error("Generation error: %s", exc)
        session["status"] = "error"
        session["error"] = str(exc)
        # Still try to compose even on partial failure
        try:
            compose_post(session, cfg, session_dir)
        except Exception:
            pass

    sm.save_session(session)
    return RedirectResponse(f"/editor/{sid}", status_code=303)


# ── Editor ────────────────────────────────────────────────────────────────────

@router.get("/editor/{session_id}", response_class=HTMLResponse)
async def editor(request: Request, session_id: str):
    templates = request.app.state.templates
    cfg = request.app.state.config
    session = sm.get_session(session_id)
    if session is None:
        return HTMLResponse("<h1>Session not found</h1>", status_code=404)

    palette = cfg["color_palettes"].get(session["palette_id"], {})
    return templates.TemplateResponse("editor.html", {
        "request": request,
        "session": session,
        "palette": palette,
        "palettes": cfg["color_palettes"],
        "font_styles": cfg["font_styles"],
        "caption_tones": cfg["caption_tones"],
        "image_types": cfg.get("image_types", {}),
        "edit_styles": cfg.get("edit_styles", {}),
        "image_styles": cfg["image_styles"],   # legacy
        "ts": int(time.time()),
    })


# ── AJAX: move layer ──────────────────────────────────────────────────────────

_TEXT_LAYERS = {"headline", "body", "hashtag"}


def _snap_logo_to_visual_position(session: dict, cfg: dict, layer: dict, sid: str) -> None:
    """On the first d-pad move, snap x/y to the actual rendered position so there's no jump."""
    edit_id  = session.get("edit_style") or session.get("image_style", "")
    edit_cfg = cfg.get("edit_styles", {}).get(edit_id) or cfg.get("image_styles", {}).get(edit_id, {})
    logo_pos = edit_cfg.get("logo_pos", "")
    if not logo_pos:
        return  # no preset — stored x/y is already the source of truth
    logo_pad = edit_cfg.get("logo_padding", 44)
    logo_max = edit_cfg.get("logo_max", [160, 90])
    max_w = layer.get("width") or logo_max[0]
    max_h = layer.get("height") or logo_max[1]
    padding = 64 if edit_cfg.get("layout") == "split" else logo_pad
    try:
        logo_path = SESSIONS_DIR / sid / "assets" / "logo.png"
        if logo_path.exists():
            logo_img = Image.open(str(logo_path)).convert("RGBA")
            scale = min(max_w / logo_img.width, max_h / logo_img.height)
            lw = max(1, round(logo_img.width * scale))
        else:
            lw = max_w  # fallback estimate
        if logo_pos == "top_right":
            layer["x"] = POST_WIDTH - padding - lw
            layer["y"] = padding
        elif logo_pos == "top_left":
            layer["x"] = padding
            layer["y"] = padding
    except Exception:
        pass  # if reading fails, proceed with whatever x/y is stored


def _sync_logo_position(session: dict, edit_cfg: dict) -> None:
    """Initialize logo_layer x/y from the edit style preset so d-pad moves from the correct visual position.
    Uses logo_max as a size estimate — the upload handler refines this with actual image dimensions."""
    logo_pos = edit_cfg.get("logo_pos", "")
    logo_max = edit_cfg.get("logo_max", [160, 90])
    ll = session.get("logo_layer", {})
    if ll.get("position_override"):
        return  # user has manually positioned it — don't reset
    # Split layouts use fixed PADDING=64; others use logo_padding from config
    padding = 64 if edit_cfg.get("layout") == "split" else edit_cfg.get("logo_padding", 44)
    if logo_pos == "top_right":
        ll["x"] = POST_WIDTH - padding - logo_max[0]
        ll["y"] = padding
    elif logo_pos == "top_left":
        ll["x"] = padding
        ll["y"] = padding
    session["logo_layer"] = ll

@router.post("/api/session/{sid}/move")
async def move_layer(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    layer_key = body.get("layer")  # "headline" | "body" | "hashtag" | "logo" | "header" | "footer"
    dx = int(body.get("dx", 0))
    dy = int(body.get("dy", 0))

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    layer_name = f"{layer_key}_layer"
    layer = session.get(layer_name, {})

    if layer_key in _TEXT_LAYERS:
        # For text layers in non-legacy zones, track as offsets from the computed position
        layer["x_offset"] = layer.get("x_offset", 0) + dx
        layer["y_offset"] = layer.get("y_offset", 0) + dy
        # Also update absolute coords for legacy-mode compatibility
        layer["x"] = layer.get("x", 540) + dx
        layer["y"] = layer.get("y", 300) + dy
    else:
        if layer_key == "logo" and not layer.get("position_override"):
            # First move: snap to actual visual position so d-pad is relative to where the logo appears
            _snap_logo_to_visual_position(session, cfg, layer, sid)
        layer["x"] = max(0, layer.get("x", 54) + dx)
        layer["y"] = max(0, layer.get("y", 54) + dy)
        if layer_key == "logo":
            layer["position_override"] = True

    session[layer_name] = layer
    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "x": layer.get("x"), "y": layer.get("y"), "ts": int(time.time())}


# ── AJAX: font size ───────────────────────────────────────────────────────────

@router.post("/api/session/{sid}/fontsize")
async def change_font_size(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    layer_key = body.get("layer")
    delta = int(body.get("delta", 2))

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    layer_name = f"{layer_key}_layer"
    layer = session.get(layer_name, {})
    current = layer.get("font_size", 30)
    layer["font_size"] = max(10, min(150, current + delta))
    session[layer_name] = layer

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "font_size": layer["font_size"], "ts": int(time.time())}


# ── AJAX: text color ──────────────────────────────────────────────────────────

@router.post("/api/session/{sid}/color")
async def change_color(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    layer_key = body.get("layer")
    color = body.get("color", "#FFFFFF")

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    layer_name = f"{layer_key}_layer"
    layer = session.get(layer_name, {})
    layer["color"] = color
    session[layer_name] = layer

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "color": color, "ts": int(time.time())}


# ── AJAX: text content ────────────────────────────────────────────────────────

@router.post("/api/session/{sid}/text")
async def update_text(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    layer_key = body.get("layer")
    text = body.get("text", "")

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    layer_name = f"{layer_key}_layer"
    layer = session.get(layer_name, {})
    layer["text"] = text
    session[layer_name] = layer

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "ts": int(time.time())}


# ── AJAX: visibility toggle ───────────────────────────────────────────────────

@router.post("/api/session/{sid}/toggle")
async def toggle_layer(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    layer_key = body.get("layer")

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    layer_name = f"{layer_key}_layer"
    layer = session.get(layer_name, {})
    layer["visible"] = not layer.get("visible", True)
    session[layer_name] = layer

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "visible": layer["visible"], "ts": int(time.time())}


# ── AJAX: asset size ──────────────────────────────────────────────────────────

@router.post("/api/session/{sid}/assetsize")
async def change_asset_size(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    layer_key = body.get("layer")
    dw = int(body.get("dw", 0))
    dh = int(body.get("dh", 0))

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    layer_name = f"{layer_key}_layer"
    layer = session.get(layer_name, {})
    layer["width"] = max(20, layer.get("width", 100) + dw)
    layer["height"] = max(20, layer.get("height", 100) + dh)
    session[layer_name] = layer

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "width": layer["width"], "height": layer["height"], "ts": int(time.time())}


# ── AJAX: regenerate caption ──────────────────────────────────────────────────

@router.post("/api/session/{sid}/regen-caption")
async def regen_caption(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    topic = body.get("topic", session["topic"])
    tone_id = body.get("caption_tone", session["caption_tone"])
    tone_cfg = cfg["caption_tones"].get(tone_id, {})
    fallback = cfg.get("fallback_caption", {"headline": "", "body": "", "hashtags": []})
    caption_prompt = build_caption_prompt(topic, tone_cfg, session["industry"],
                                         brand_context=session.get("brand_description", ""))
    caption = generate_caption(caption_prompt, fallback)

    session["caption"] = caption
    session["topic"] = topic
    session["caption_tone"] = tone_id
    session["social_caption"] = caption.get("social_caption", "")
    session["headline_layer"]["text"] = caption["headline"]
    session["body_layer"]["text"] = caption["body"]
    session["hashtag_layer"]["text"] = " ".join(caption["hashtags"])

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "caption": caption, "social_caption": session["social_caption"], "ts": int(time.time())}


# ── Analyze brand description → recommend settings ───────────────────────────

@router.post("/api/analyze-brand")
async def analyze_brand(request: Request):
    cfg = request.app.state.config
    body = await request.json()
    description = body.get("description", "").strip()
    topic       = body.get("topic", "").strip()

    if not description:
        return {"error": "description required"}

    fallback = {
        "industry":     "business_corporate",
        "image_type":   "photo_lifestyle",
        "edit_style":   "editorial_clean",
        "caption_tone": "business_friendly",
        "palette_id":   "business_professional",
        "font_style":   "sans_serif_bold",
    }

    prompt = build_brand_analysis_prompt(
        description, topic,
        industries    = list(cfg["industries"].keys()),
        image_types   = list(cfg.get("image_types", {}).keys()),
        edit_styles   = list(cfg.get("edit_styles", {}).keys()),
        caption_tones = list(cfg["caption_tones"].keys()),
        palettes      = list(cfg["color_palettes"].keys()),
        font_styles   = list(cfg["font_styles"].keys()),
    )

    raw = generate_brand_config(prompt, fallback)

    # Validate every field against the real config keys
    valid = {
        "industry":     list(cfg["industries"].keys()),
        "image_type":   list(cfg.get("image_types", {}).keys()),
        "edit_style":   list(cfg.get("edit_styles", {}).keys()),
        "caption_tone": list(cfg["caption_tones"].keys()),
        "palette_id":   list(cfg["color_palettes"].keys()),
        "font_style":   list(cfg["font_styles"].keys()),
    }
    result = {k: (raw.get(k) if raw.get(k) in v else fallback[k]) for k, v in valid.items()}
    return {"ok": True, **result}


# ── AJAX: change post layout (edit_style) ────────────────────────────────────

@router.post("/api/session/{sid}/edit-style")
async def change_edit_style(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    edit_style_id = body.get("edit_style_id", "")

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    edit_cfg = cfg.get("edit_styles", {}).get(edit_style_id, {})
    if not edit_cfg:
        return {"error": "unknown edit style"}

    session["edit_style"] = edit_style_id

    # Sync text colors to the new layout's text_color_mode
    palette = cfg["color_palettes"].get(session["palette_id"], {})
    text_color_mode = edit_cfg.get("text_color_mode", "white")
    if text_color_mode == "dark":
        session["headline_layer"]["color"] = palette.get("primary", "#1a2e55")
        session["body_layer"]["color"]     = palette.get("secondary", "#4A5568")
    elif text_color_mode == "white_pure":
        session["headline_layer"]["color"] = "#FFFFFF"
        session["body_layer"]["color"]     = "#F2F2F2"
    else:
        session["headline_layer"]["color"] = palette.get("text_primary", "#FFFFFF")
        session["body_layer"]["color"]     = palette.get("text_secondary", "#CCCCCC")

    # Reset logo position for new layout (unless user has manually positioned it)
    _sync_logo_position(session, edit_cfg)

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "ts": int(time.time())}


# ── AJAX: contact bar ────────────────────────────────────────────────────────

@router.post("/api/session/{sid}/contact")
async def update_contact_bar(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    cb = session.get("contact_bar_layer", {})
    if "phone"    in body: cb["phone"]    = str(body["phone"])
    if "email"    in body: cb["email"]    = str(body["email"])
    if "bg_color" in body: cb["bg_color"] = str(body["bg_color"])
    if "enabled"  in body: cb["enabled"]  = bool(body["enabled"])
    session["contact_bar_layer"] = cb

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "ts": int(time.time())}


# ── AJAX: regenerate social caption + hashtags ────────────────────────────────

@router.post("/api/session/{sid}/regen-social")
async def regen_social(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    tone_id = body.get("caption_tone", session["caption_tone"])
    tone_cfg = cfg["caption_tones"].get(tone_id, {})
    fallback = {
        "social_caption": session.get("social_caption", "Your story starts here."),
        "hashtags": session.get("caption", {}).get("hashtags", ["#PostForge"]),
    }
    prompt = build_social_prompt(session["topic"], tone_cfg, session["industry"])
    result = generate_social(prompt, fallback)

    session["social_caption"] = result["social_caption"]
    session["caption"]["hashtags"] = result["hashtags"]
    sm.save_session(session)
    return {"ok": True, "social_caption": result["social_caption"],
            "hashtags": result["hashtags"], "ts": int(time.time())}


# ── AJAX: font family ─────────────────────────────────────────────────────────

@router.post("/api/session/{sid}/fontfamily")
async def change_font_family(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    layer_key = body.get("layer")   # "headline" | "body" | "hashtag"
    font_style_id = body.get("font_style_id", "")

    session = sm.get_session(sid)
    if not session:
        return {"error": "not found"}

    font_cfg = cfg["font_styles"].get(font_style_id, {})
    if not font_cfg:
        return {"error": "unknown font style"}

    # Headline role uses the bold/headline file; body and hashtag use the body file
    if layer_key == "headline":
        font_file = font_cfg.get("headline_file") or font_cfg.get("fallback_headline", "arial.ttf")
    else:
        font_file = font_cfg.get("body_file") or font_cfg.get("fallback_body", "arial.ttf")

    layer_name = f"{layer_key}_layer"
    layer = session.get(layer_name, {})
    layer["font_file"] = font_file
    layer["font_style_id"] = font_style_id
    session[layer_name] = layer

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "font_file": font_file, "ts": int(time.time())}


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/api/session/{sid}/export")
async def export_image(request: Request, sid: str):
    from fastapi.responses import FileResponse
    path = SESSIONS_DIR / sid / "composed.png"
    if not path.exists():
        return {"error": "not found"}
    session = sm.get_session(sid)
    if session:
        _save_to_output(session)
    return FileResponse(
        str(path),
        media_type="image/png",
        filename=f"postforge_{sid}.png",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _presave_asset(upload: Optional[UploadFile], session: dict, session_dir, asset_type: str) -> None:
    """Save a pre-uploaded asset from the generate form into the session assets dir."""
    if not upload or not upload.filename:
        return
    try:
        raw = upload.file.read()
        if not raw:
            return
        if asset_type == "background":
            dest = session_dir / "base_image.png"
            session["has_custom_bg"] = True
        else:
            dest = session_dir / "assets" / f"{asset_type}.png"
            session[f"has_{asset_type}"] = True
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        img.save(str(dest), "PNG")
        log.info("Pre-saved %s asset -> %s", asset_type, dest)
    except Exception as exc:
        log.warning("Could not pre-save %s: %s", asset_type, exc)


def _recompose(session: dict, cfg: dict, sid: str) -> None:
    try:
        session_dir = SESSIONS_DIR / sid
        compose_post(session, cfg, session_dir)
    except Exception as exc:
        log.error("Recompose error: %s", exc)


def _save_to_output(session: dict) -> None:
    """Copy the composed image into the root output/ folder."""
    src = SESSIONS_DIR / session["session_id"] / "composed.png"
    if not src.exists():
        return
    ensure_dir(OUTPUT_DIR)
    slug = sanitize_filename(session.get("topic", "post"))[:40]
    ts = int(time.time())
    dest = OUTPUT_DIR / f"{ts}_{session['session_id']}_{slug}.png"
    shutil.copy2(src, dest)
    log.info("Saved to output -> %s", dest.name)
