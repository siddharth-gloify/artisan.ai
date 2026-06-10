"""Handle logo / header / footer uploads."""

import io
import time
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import JSONResponse
from PIL import Image

from src.core import session_manager as sm
from src.core.composition import compose_post
from src.utils.constants import SESSIONS_DIR
from src.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter()

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


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
