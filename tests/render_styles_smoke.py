"""Smoke-render every edit style to output/style_previews/ for visual review.

Run from postforge/:  python -m tests.render_styles_smoke
Uses a real session base image if one exists, else the gradient fallback.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server.main import load_config  # noqa: E402
from src.core.composition import compose_post  # noqa: E402

BASE_DIR = Path(__file__).parent.parent
SESSIONS_DIR = BASE_DIR / "src" / "storage" / "sessions"
OUT_DIR = BASE_DIR / "output" / "style_previews"
TMP_DIR = BASE_DIR / "src" / "storage" / "sessions" / "_smoke"


def find_base_image() -> Path | None:
    for sdir in sorted(SESSIONS_DIR.iterdir()):
        cand = sdir / "base_image.png"
        if cand.exists():
            return cand
    return None


def make_session(edit_style: str, cfg: dict, palette_id: str) -> dict:
    edit_cfg = cfg["edit_styles"][edit_style]
    palette = cfg["color_palettes"][palette_id]
    mode = edit_cfg.get("text_color_mode", "white")
    if mode == "dark":
        hl_color, body_color = palette["primary"], palette["secondary"]
    elif mode == "white_pure":
        hl_color, body_color = "#FFFFFF", "#F2F2F2"
    else:
        hl_color, body_color = palette["text_primary"], palette["text_secondary"]
    return {
        "session_id": "_smoke",
        "edit_style": edit_style,
        "image_style": edit_style,
        "palette_id": palette_id,
        "font_style": "sans_serif_bold",
        "industry": "lifestyle",
        "has_logo": False,
        "has_header": False,
        "has_footer": False,
        "headline_layer": {
            "text": "Crafted For The Way You Live",
            "x": 540, "y": 280, "x_offset": 0, "y_offset": 0,
            "font_size": edit_cfg.get("headline_default_size", 64),
            "color": hl_color,
            "visible": True,
        },
        "body_layer": {
            "text": "Discover our new collection — designed with intention, made to last.",
            "x": 540, "y": 520, "x_offset": 0, "y_offset": 0,
            "font_size": edit_cfg.get("body_default_size", 30),
            "color": body_color,
            "visible": True,
        },
        "hashtag_layer": {"text": "", "visible": True},
        "tag_layer": {
            "text": "NEW ARRIVAL", "visible": True,
            "bg_color": palette["accent"], "text_color": "#FFFFFF", "font_size": 24,
        },
        "logo_layer": {"x": 876, "y": 44, "width": 120, "height": 120,
                       "visible": True, "opacity": 1.0, "position_override": False},
        "header_layer": {"visible": False},
        "footer_layer": {"visible": False},
        "contact_bar_layer": {"enabled": False, "phone": "", "email": "", "visible": True},
    }


def main() -> None:
    cfg = load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    base = find_base_image()
    if base:
        shutil.copy(base, TMP_DIR / "base_image.png")
        print(f"Using base image: {base}")
    else:
        print("No base image found — using gradient fallback")

    palettes = {
        "premium": "luxury_dark",
        "commercial": "business_professional",
        "general": "neutral_elegant",
        "split": "dark_blue_tech",
    }

    failures = []
    for style_id, style in cfg["edit_styles"].items():
        palette_id = palettes.get(style.get("category", "general"), "neutral_elegant")
        session = make_session(style_id, cfg, palette_id)
        t0 = time.perf_counter()
        try:
            out = compose_post(session, cfg, TMP_DIR)
            ms = (time.perf_counter() - t0) * 1000
            dest = OUT_DIR / f"{style_id}.png"
            shutil.copy(out, dest)
            print(f"  OK  {style_id:<22} {ms:6.0f} ms -> {dest.name}")
        except Exception as exc:  # noqa: BLE001
            failures.append((style_id, exc))
            print(f"FAIL  {style_id:<22} {exc!r}")

    shutil.rmtree(TMP_DIR, ignore_errors=True)
    print(f"\n{len(cfg['edit_styles']) - len(failures)}/{len(cfg['edit_styles'])} styles rendered to {OUT_DIR}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
