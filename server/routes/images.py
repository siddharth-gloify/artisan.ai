"""Regenerate base image."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.core import session_manager as sm
from src.core.composition import compose_post
from src.core.image_processor import generate_base_image
from src.core.prompt_formatter import build_image_prompt
from src.utils.constants import SESSIONS_DIR
from src.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.post("/api/session/{sid}/regen-image")
async def regen_image(request: Request, sid: str):
    cfg = request.app.state.config
    body = await request.json()
    session = sm.get_session(sid)
    if not session:
        return JSONResponse({"error": "session not found"}, status_code=404)

    style_id = body.get("image_style", session["image_style"])
    palette_id = body.get("palette_id", session["palette_id"])
    tier = body.get("image_tier", session.get("image_tier", "normal"))

    image_type_cfg = (cfg.get("image_types", {}).get(style_id) or
                      cfg.get("image_styles", {}).get(style_id, {}))
    palette = cfg["color_palettes"].get(palette_id, {})

    img_prompt = build_image_prompt(session["topic"], image_type_cfg, palette)
    base_path = SESSIONS_DIR / sid / "base_image.png"

    success = await generate_base_image(img_prompt, palette, base_path, tier=tier)

    # Update session if style/palette/tier changed
    session["image_style"] = style_id
    session["palette_id"] = palette_id
    session["image_tier"] = tier
    sm.save_session(session)

    try:
        compose_post(session, cfg, SESSIONS_DIR / sid)
    except Exception as exc:
        log.error("Recompose after image regen failed: %s", exc)

    import time
    return {"ok": True, "llm_used": success, "ts": int(time.time())}
