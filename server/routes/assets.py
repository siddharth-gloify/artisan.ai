"""Handle logo / header / footer uploads."""

import io
import time
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import JSONResponse
from PIL import Image

from src.core import session_manager as sm
from src.core.composition import compose_post
from src.utils.constants import SESSIONS_DIR, POST_WIDTH
from src.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter()

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _init_logo_position_from_image(session: dict, cfg: dict, raw: bytes) -> None:
    """Compute the exact rendered logo position using actual image dimensions and store it.
    This ensures the d-pad starts from the correct visual position instead of jumping."""
    ll = session.get("logo_layer", {})
    if ll.get("position_override"):
        return  # user already moved it manually — don't reset

    edit_id  = session.get("edit_style") or session.get("image_style", "")
    edit_cfg = cfg.get("edit_styles", {}).get(edit_id) or cfg.get("image_styles", {}).get(edit_id, {})
    logo_pos = edit_cfg.get("logo_pos", "")
    logo_pad = edit_cfg.get("logo_padding", 44)
    logo_max = edit_cfg.get("logo_max", [160, 90])
    max_w = ll.get("width") or logo_max[0]
    max_h = ll.get("height") or logo_max[1]

    try:
        logo_img = Image.open(io.BytesIO(raw)).convert("RGBA")
        scale = min(max_w / logo_img.width, max_h / logo_img.height)
        lw = max(1, round(logo_img.width * scale))

        # Split layouts use a fixed PADDING=64; standard layouts use logo_padding from config
        padding = 64 if edit_cfg.get("layout") == "split" else logo_pad
        if logo_pos == "top_right":
            ll["x"] = POST_WIDTH - padding - lw
            ll["y"] = padding
        elif logo_pos == "top_left":
            ll["x"] = padding
            ll["y"] = padding
        # no logo_pos: leave x/y at whatever they are (user-defined or defaults)
        session["logo_layer"] = ll
    except Exception as exc:
        log.warning("Could not compute logo position from image: %s", exc)


def _save_as_png(data: bytes, dest: Path) -> None:
    """Open any image format and re-save as RGBA PNG for consistent Pillow handling."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img.save(str(dest), "PNG")


@router.post("/api/session/{sid}/upload/{asset_type}")
async def upload_asset(
    request: Request,
    sid: str,
    asset_type: str,  # "logo" | "header" | "footer" | "background"
    file: UploadFile = File(...),
):
    if asset_type not in ("logo", "header", "footer", "background"):
        return JSONResponse({"error": "invalid asset type"}, status_code=400)

    if file.content_type not in ALLOWED_TYPES:
        return JSONResponse({"error": "unsupported file type"}, status_code=400)

    session = sm.get_session(sid)
    if not session:
        return JSONResponse({"error": "session not found"}, status_code=404)

    cfg = request.app.state.config
    asset_dir = SESSIONS_DIR / sid / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)

    if asset_type == "background":
        dest = SESSIONS_DIR / sid / "base_image.png"
        session["has_custom_bg"] = True
    else:
        dest = asset_dir / f"{asset_type}.png"
        session[f"has_{asset_type}"] = True

    # Read the full file async, then normalize to RGBA PNG
    raw = await file.read()
    try:
        _save_as_png(raw, dest)
    except Exception as exc:
        log.error("Could not process uploaded image for %s: %s", asset_type, exc)
        return JSONResponse({"error": f"Could not read image: {exc}"}, status_code=400)

    # For logo: compute exact rendered position from actual image dimensions so
    # the d-pad starts from the correct visual location (not the 54,54 default).
    if asset_type == "logo":
        _init_logo_position_from_image(session, cfg, raw)

    sm.save_session(session)

    compose_error = None
    try:
        compose_post(session, cfg, SESSIONS_DIR / sid)
    except Exception as exc:
        compose_error = str(exc)
        log.error("Recompose after upload failed: %s", exc)

    resp: dict = {"ok": True, "asset": asset_type, "ts": int(time.time())}
    if compose_error:
        resp["warning"] = compose_error
    return resp


@router.delete("/api/session/{sid}/upload/{asset_type}")
async def remove_asset(request: Request, sid: str, asset_type: str):
    session = sm.get_session(sid)
    if not session:
        return JSONResponse({"error": "session not found"}, status_code=404)

    cfg = request.app.state.config

    if asset_type == "background":
        path = SESSIONS_DIR / sid / "base_image.png"
        session["has_custom_bg"] = False
    else:
        path = SESSIONS_DIR / sid / "assets" / f"{asset_type}.png"
        session[f"has_{asset_type}"] = False

    if path.exists():
        path.unlink()

    sm.save_session(session)

    try:
        compose_post(session, cfg, SESSIONS_DIR / sid)
    except Exception as exc:
        log.error("Recompose after delete failed: %s", exc)

    return {"ok": True, "removed": asset_type, "ts": int(time.time())}
