import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

app = FastAPI(title="PostForge", version="0.1.0")

BASE_DIR = Path(__file__).parent.parent

# ── Ensure runtime dirs exist before mounting ─────────────────────────────────
for _d in [
    BASE_DIR / "src" / "storage" / "sessions",
    BASE_DIR / "src" / "storage" / "outputs",
    BASE_DIR / "output",
]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Static files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount(
    "/files",
    StaticFiles(directory=str(BASE_DIR / "src" / "storage")),
    name="files",
)
app.mount(
    "/output",
    StaticFiles(directory=str(BASE_DIR / "output")),
    name="output",
)

# ── Jinja2 templates ──────────────────────────────────────────────────────────
templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "templates"))
app.state.templates = templates

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_DIR = BASE_DIR / "src" / "config"


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> dict:
    palettes_raw  = _load_yaml("color_palettes.yaml")
    styles_raw    = _load_yaml("image_styles.yaml")
    prompts_raw   = _load_yaml("prompts.yaml")
    templates_raw = _load_yaml("templates.yaml")
    return {
        "color_palettes":        palettes_raw.get("palettes", {}),
        "palette_categories":    palettes_raw.get("categories", {}),
        "image_styles":          styles_raw.get("image_styles", {}),
        "style_categories":      styles_raw.get("style_categories", {}),
        "caption_tones":         prompts_raw.get("caption_tones", {}),
        "fallback_caption":      prompts_raw.get("fallback_caption", {}),
        "industries":            templates_raw.get("industries", {}),
        "font_styles":           templates_raw.get("font_styles", {}),
        "quick_start_templates": templates_raw.get("quick_start_templates", {}),
    }


app.state.config = load_config()

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    cfg = app.state.config
    output_dir = BASE_DIR / "output"
    saved = sorted(output_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "status": "ok",
        "config": {
            "palettes":   len(cfg["color_palettes"]),
            "styles":     len(cfg["image_styles"]),
            "tones":      len(cfg["caption_tones"]),
            "industries": len(cfg["industries"]),
            "fonts":      len(cfg["font_styles"]),
        },
        "keys": {
            "text_key":  bool(os.getenv("OPENROUTER_TEXT_KEY")),
            "image_key": bool(os.getenv("OPENROUTER_IMAGE_KEY")),
        },
        "output": {
            "total": len(saved),
            "latest": saved[0].name if saved else None,
        },
    }


@app.get("/outputs")
async def list_outputs(request: Request):
    output_dir = BASE_DIR / "output"
    files = sorted(output_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "total": len(files),
        "files": [
            {
                "name": f.name,
                "url": f"/output/{f.name}",
                "size_kb": round(f.stat().st_size / 1024, 1),
            }
            for f in files
        ],
    }


# ── Routes ────────────────────────────────────────────────────────────────────
from server.routes import sessions, images, assets  # noqa: E402

app.include_router(sessions.router)
app.include_router(images.router)
app.include_router(assets.router)
