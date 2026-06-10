import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.constants import SESSIONS_DIR, POST_WIDTH, POST_HEIGHT
from src.utils.helpers import ensure_dir
from src.utils.logger import get_logger

log = get_logger(__name__)


def _session_dir(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


def _session_file(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def create_session(industry: str, image_style: str, caption_tone: str,
                   palette_id: str, font_style: str, topic: str,
                   image_tier: str = "normal") -> dict:
    session_id = str(uuid.uuid4())[:8]
    session_dir = _session_dir(session_id)
    ensure_dir(session_dir)
    ensure_dir(session_dir / "assets")

    session = {
        "session_id": session_id,
        "created_at": datetime.utcnow().isoformat(),
        "status": "pending",
        "image_tier": image_tier,
        "industry": industry,
        "image_style": image_style,
        "caption_tone": caption_tone,
        "palette_id": palette_id,
        "font_style": font_style,
        "topic": topic,
        "caption": {"headline": "", "body": "", "social_caption": "", "hashtags": []},
        "social_caption": "",
        "has_logo": False,
        "has_header": False,
        "has_footer": False,
        "has_custom_bg": False,
        "headline_layer": {
            "text": "",
            "x": POST_WIDTH // 2,
            "y": 280,
            "font_size": 64,
            "color": "#FFFFFF",
            "align": "center",
            "visible": True,
        },
        "body_layer": {
            "text": "",
            "x": POST_WIDTH // 2,
            "y": 520,
            "font_size": 30,
            "color": "#EEEEEE",
            "align": "center",
            "visible": True,
        },
        "hashtag_layer": {
            "text": "",
            "x": POST_WIDTH // 2,
            "y": POST_HEIGHT - 120,
            "font_size": 22,
            "color": "#AAAAAA",
            "align": "center",
            "visible": True,
        },
        "tag_layer": {
            "text": "",
            "visible": True,
            "bg_color": "#B48C3C",
            "text_color": "#FFFFFF",
            "font_size": 26,
        },
        "logo_layer": {
            "x": 54,
            "y": 54,
            "width": 120,
            "height": 120,
            "visible": True,
            "opacity": 1.0,
        },
        "header_layer": {
            "x": 0,
            "y": 0,
            "width": POST_WIDTH,
            "height": 160,
            "visible": True,
            "opacity": 1.0,
        },
        "footer_layer": {
            "x": 0,
            "y": POST_HEIGHT - 160,
            "width": POST_WIDTH,
            "height": 160,
            "visible": True,
            "opacity": 1.0,
        },
    }

    save_session(session)
    return session


def get_session(session_id: str) -> Optional[dict]:
    path = _session_file(session_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_session(session: dict) -> None:
    path = _session_file(session["session_id"])
    path.write_text(json.dumps(session, indent=2), encoding="utf-8")


def update_session(session_id: str, updates: dict) -> dict:
    session = get_session(session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")
    session.update(updates)
    save_session(session)
    return session


def session_asset_dir(session_id: str) -> Path:
    return _session_dir(session_id) / "assets"


def composed_path(session_id: str) -> Path:
    return _session_dir(session_id) / "composed.png"
