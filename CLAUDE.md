# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
make install            # pip install -r requirements.txt

# Run dev server (from postforge/)
make dev                # uvicorn server.main:app --reload --host 127.0.0.1 --port 8000

# Tests
make test               # pytest tests/ -v
pytest tests/test_llm_text.py -v -s   # single test file, with stdout

# Lint
make lint               # ruff check src server tests
```

Copy `.env.example` → `.env` before starting. Required env vars: `OPENROUTER_TEXT_KEY`, `OPENROUTER_IMAGE_KEY`. Optional: `OPENROUTER_TEXT_MODEL` (defaults to `deepseek/deepseek-chat`).

## Architecture

### Request flow
1. `POST /generate` (in `server/routes/sessions.py`) — entry point. Creates a session, calls text gen + image gen, then composes and redirects to `/editor/{sid}`.
2. `/editor/{sid}` — serves the editor UI. Every edit triggers an AJAX call to `/api/session/{sid}/*` which mutates the session and calls `compose_post()` again.
3. `GET /api/session/{sid}/export` — copies `composed.png` to `output/` and returns it as a download.

### Core modules
- `src/core/composition.py` — Pillow rendering engine. `compose_post()` is the main entry point. Two distinct paths: standard (overlay text on base image) and `split` (solid-color top zone + photo bottom zone via `_compose_split_layout`).
- `src/core/text_generator.py` — OpenRouter via OpenAI-compatible SDK. Returns `{headline, body, hashtags}` JSON; falls back to hardcoded dict if key missing.
- `src/core/image_processor.py` — OpenRouter HTTP (Google Gemini image models). Three tiers: `normal` / `pro` / `max`. Falls back to Pillow gradient if key missing or call fails.
- `src/core/prompt_formatter.py` — builds LLM prompts from config. Industry → scene description; style → visual aesthetic; palette colors injected into image prompt.
- `src/core/session_manager.py` — flat JSON CRUD. Sessions are 8-char UUID slugs.
- `server/routes/assets.py` — asset uploads (`/api/session/{sid}/upload/{asset_type}`). Normalizes all uploads to RGBA PNG before saving.

### Config YAMLs (`src/config/`)
- `color_palettes.yaml` — named palettes with `background`, `primary`, `secondary`, `text_primary`, `text_secondary`, `accent`, `gradient_end`
- `image_styles.yaml` — visual styles with `layout` (`split` or absent), `overlay_color`, `overlay_opacity`, `image_prompt`, `photo_split`
- `prompts.yaml` — `caption_tones` (each has `llm_prompt` template with `{topic}` / `{industry}` placeholders) and `fallback_caption`
- `templates.yaml` — `industries`, `font_styles` (each has `headline_file`, `body_file`, `fallback_*`), `quick_start_templates`

### Session structure
Sessions (`src/storage/sessions/{id}/session.json`) carry layer state for: `headline_layer`, `body_layer`, `hashtag_layer`, `tag_layer` (split layout only), `logo_layer`, `header_layer`, `footer_layer`. Each layer has position (`x`, `y`), size, `visible`, `color`/`font_size` where applicable. Asset files live at `sessions/{id}/assets/{logo,header,footer}.png`; background at `sessions/{id}/base_image.png`.

### Key patterns
- Post canvas is always 1080×1350 (4:5 Instagram ratio). Constants in `src/utils/constants.py`.
- Font resolution order: `static/fonts/` → `C:/Windows/Fonts/` (Windows) / `/usr/share/fonts` (Linux) → Pillow default.
- `compose_post()` is called on every editor AJAX mutation — it is synchronous and fast (Pillow only; no network calls).
- Image tier is stored on the session; re-generating the image (`POST /api/session/{sid}/regen-image`) re-reads it from the request body or falls back to the stored value.
- Config is loaded once at startup into `app.state.config` and passed through to all route handlers.
- Static files served at `/static` (CSS/JS/fonts), `/files` (session storage), `/output` (exported PNGs).
