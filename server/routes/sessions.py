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
from src.core.prompt_formatter import build_caption_prompt, build_image_prompt
from src.core.text_generator import generate_caption
from src.utils.constants import SESSIONS_DIR, OUTPUT_DIR
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
        "image_styles": cfg["image_styles"],
        "style_categories": cfg["style_categories"],
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
    industry: str = Form(...),
    image_style: str = Form(...),
    caption_tone: str = Form(...),
    palette_id: str = Form(...),
    font_style: str = Form(...),
    topic: str = Form(...),
    image_tier: str = Form("normal"),
    logo_file: Optional[UploadFile] = File(None),
    header_file: Optional[UploadFile] = File(None),
    footer_file: Optional[UploadFile] = File(None),
    bg_file: Optional[UploadFile] = File(None),
):
    cfg = request.app.state.config
    ensure_dir(SESSIONS_DIR)

    # 1. Create session
    session = sm.create_session(
        industry=industry,
        image_style=image_style,
        caption_tone=caption_tone,
        palette_id=palette_id,
        font_style=font_style,
        topic=topic,
        image_tier=image_tier,
    )
    sid = session["session_id"]
    session_dir = SESSIONS_DIR / sid

    # Save any pre-uploaded assets from the index page form
    _presave_asset(logo_file,   session, session_dir, "logo")
    _presave_asset(header_file, session, session_dir, "header")
    _presave_asset(footer_file, session, session_dir, "footer")
    _presave_asset(bg_file,     session, session_dir, "background")

    try:
        style_cfg = cfg["image_styles"].get(image_style, {})

        # 2. Generate caption
        tone_cfg = cfg["caption_tones"].get(caption_tone, {})
        fallback = cfg.get("fallback_caption", {
            "headline": "Make it happen",
            "body": "Your story starts here.",
            "hashtags": ["#PostForge"],
        })
        caption_prompt = build_caption_prompt(topic, tone_cfg, industry)
        caption = generate_caption(caption_prompt, fallback)
        session["caption"] = caption

        # 3. Sync text layers with generated caption
        palette = cfg["color_palettes"].get(palette_id, {})
        text_color = palette.get("text_primary", "#FFFFFF")
        text_color_2 = palette.get("text_secondary", "#CCCCCC")

        session["headline_layer"]["text"] = caption["headline"]
        session["headline_layer"]["color"] = text_color
        session["body_layer"]["text"] = caption["body"]
        session["body_layer"]["color"] = text_color_2
        session["hashtag_layer"]["text"] = " ".join(caption["hashtags"])

        # Populate tag pill for split layouts
        if style_cfg.get("layout") == "split":
            hashtags = caption.get("hashtags", [])
            first_tag = hashtags[0].lstrip("#") if hashtags else " ".join(topic.split()[:3])
            session["tag_layer"]["text"] = first_tag.upper()
            session["tag_layer"]["bg_color"] = palette.get("accent", "#B48C3C")
            session["tag_layer"]["text_color"] = palette.get("text_primary", "#FFFFFF")

        # 4. Generate base image
        img_prompt = build_image_prompt(topic, style_cfg, palette, industry=industry)
        base_path = session_dir / "base_image.png"
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
        "image_styles": cfg["image_styles"],
        "ts": int(time.time()),
    })


# ── AJAX: move layer ──────────────────────────────────────────────────────────

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
    layer["x"] = max(0, layer.get("x", 540) + dx)
    layer["y"] = max(0, layer.get("y", 300) + dy)
    session[layer_name] = layer

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "x": layer["x"], "y": layer["y"], "ts": int(time.time())}


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
    caption_prompt = build_caption_prompt(topic, tone_cfg, session["industry"])
    caption = generate_caption(caption_prompt, fallback)

    session["caption"] = caption
    session["topic"] = topic
    session["caption_tone"] = tone_id
    session["headline_layer"]["text"] = caption["headline"]
    session["body_layer"]["text"] = caption["body"]
    session["hashtag_layer"]["text"] = " ".join(caption["hashtags"])

    sm.save_session(session)
    _recompose(session, cfg, sid)
    return {"ok": True, "caption": caption, "ts": int(time.time())}


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
