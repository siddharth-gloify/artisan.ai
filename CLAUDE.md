# CLAUDE.md — PostForge

AI-powered Instagram post generator (1080×1350 px). FastAPI + Jinja2 backend with Pillow composition engine.

---

## Quick start

```bash
# from postforge/
make install   # pip install -r requirements.txt
make dev       # uvicorn server.main:app --reload --host 127.0.0.1 --port 8000
make test      # pytest tests/ -v
make lint      # ruff check src server tests
```

Copy `.env.example` → `.env`. Required: `OPENROUTER_TEXT_KEY`, `OPENROUTER_IMAGE_KEY`.
Optional: `OPENROUTER_TEXT_MODEL` (defaults to `deepseek/deepseek-chat`).

Health check: `GET /health` returns config key counts + API key presence.

---

## Folder map

```
postforge/
├── server/
│   ├── main.py                  # FastAPI app, config loader, static mounts
│   └── routes/
│       ├── sessions.py          # ALL main routes: home, generate, editor, AJAX endpoints
│       ├── assets.py            # Logo / header / footer / background uploads + deletes
│       ├── images.py            # POST /api/session/{sid}/regen-image
│       └── text.py              # (text-only utility routes)
│
├── src/
│   ├── core/
│   │   ├── composition.py       # Pillow engine — compose_post() is the main entry point
│   │   ├── session_manager.py   # JSON CRUD — create / get / save / update sessions
│   │   ├── text_generator.py    # OpenRouter → caption JSON {headline, body, hashtags}
│   │   ├── image_processor.py   # OpenRouter → Gemini image models, base64 → PNG
│   │   └── prompt_formatter.py  # Builds all LLM prompts from config + session data
│   │
│   ├── config/                  # All YAML configs loaded once at startup
│   │   ├── edit_styles.yaml     # Layout presets (text zone, overlay, logo pos, etc.)
│   │   ├── color_palettes.yaml  # Named palettes (background, primary, accent, ...)
│   │   ├── image_types.yaml     # What the AI generates (photo_lifestyle, etc.)
│   │   ├── image_styles.yaml    # Legacy combined styles (kept for compat)
│   │   ├── templates.yaml       # Industries, font_styles, quick_start_templates
│   │   └── prompts.yaml         # caption_tones (each with llm_prompt template)
│   │
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── base.html            # Layout shell (navbar, CSS/JS links)
│   │   ├── index.html           # Home / generate form
│   │   ├── editor.html          # Full editor UI (controls panel + preview)
│   │   └── components/          # Partial snippets (navbar, preview, uploader, text_editor)
│   │
│   ├── storage/
│   │   └── sessions/{sid}/      # Per-session directory
│   │       ├── session.json     # Layer state + metadata
│   │       ├── composed.png     # Last rendered output (served at /files/...)
│   │       ├── base_image.png   # AI-generated or user-uploaded background
│   │       └── assets/
│   │           ├── logo.png
│   │           ├── header.png
│   │           └── footer.png
│   │
│   └── utils/
│       ├── constants.py         # POST_WIDTH=1080, POST_HEIGHT=1350, dir paths
│       ├── helpers.py           # ensure_dir, sanitize_filename
│       ├── validators.py        # Input validation helpers
│       └── logger.py            # Structured logger
│
├── static/
│   ├── css/main.css             # Dark theme UI (design tokens: --bg, --surface, --primary)
│   ├── js/main.js               # Frontend JS
│   └── fonts/                   # .ttf files — resolved before Windows/Linux system fonts
│
├── output/                      # Exported PNGs land here (served at /output/)
├── tests/
│   ├── test_llm_text.py
│   ├── test_llm_image.py
│   └── conftest.py
│
├── .env / .env.example
├── Makefile
├── requirements.txt
└── pyproject.toml
```

---

## Request flow (end to end)

```
POST /generate
  → create_session()              session_manager.py
  → _sync_logo_position()         seeds logo x/y from edit style config
  → generate_caption()            text_generator.py → OpenRouter LLM
  → generate_base_image()         image_processor.py → OpenRouter Gemini
  → compose_post()                composition.py → Pillow → saves composed.png
  → redirect /editor/{sid}

GET /editor/{sid}
  → renders editor.html (Jinja2 SSR, all layer state injected)
  → user edits → AJAX to /api/session/{sid}/*
      → session mutated → sm.save_session() → compose_post() → returns {ts}
      → JS refreshes <img> with ?t= cache-bust

GET /api/session/{sid}/export
  → copies composed.png to output/ → returns file download
```

---

## Composition engine (`src/core/composition.py`)

`compose_post(session, config, session_dir)` is the only public entry point. Called synchronously on every edit (Pillow only, no network).

**Two rendering paths:**

| Condition | Path | Key function |
|-----------|------|--------------|
| `edit_cfg["layout"] == "split"` | Split | `_compose_split_layout()` — solid-color top zone + photo bottom half |
| All other layouts | Standard / full-bleed | Inline in `compose_post()` |

**Standard layout render order:**
1. Base image (AI PNG or palette gradient fallback)
2. Overlay (gradient_top, gradient_bottom, solid, or none — from edit_cfg)
3. Header asset (if uploaded)
4. Footer asset (if uploaded)
5. Logo (position: `position_override` flag → stored x/y; else `logo_pos` preset from edit_cfg)
6. Headline + body text (position: `text_zone` from edit_cfg + `x_offset`/`y_offset` from layer)
7. Contact bar (if enabled)

**Logo position logic (important):**
- All edit styles have `logo_pos: top_right`. At session creation, `_sync_logo_position()` seeds `logo_layer.x/y` using `logo_max` as a size estimate.
- On first logo upload, `_init_logo_position_from_image()` recomputes from actual image dimensions.
- On first d-pad click, `_snap_logo_to_visual_position()` reads the logo file and snaps to exact current visual position before applying delta.
- Once moved, `logo_layer.position_override = True` — composition uses stored x/y permanently.

**Text position logic:**
- For `text_zone == "legacy"`: uses `layer.x` / `layer.y` directly (absolute).
- For all other zones (top, middle, bottom, center): computes from zone spec, then adds `layer.x_offset` / `layer.y_offset` (start at 0, updated by d-pad).

---

## AJAX API reference (`server/routes/sessions.py`)

All endpoints are `POST /api/session/{sid}/<action>` and return `{ok, ts, ...}`.
The `ts` (unix timestamp) is used by the editor JS to cache-bust the preview image.

| Endpoint | Body | Effect |
|----------|------|--------|
| `move` | `{layer, dx, dy}` | Moves any layer. Text layers update x_offset/y_offset + absolute x/y. Logo sets position_override. |
| `fontsize` | `{layer, delta}` | ±2px font size, clamped 10–150 |
| `color` | `{layer, color}` | Hex color for text layers |
| `toggle` | `{layer}` | Flip `visible` on any layer (text or asset) |
| `assetsize` | `{layer, dw, dh}` | Resize logo/header/footer. Logo: dw=dh=±20. Header/footer: dh only. |
| `text` | `{layer, text}` | Update headline or body text (debounced 600ms) |
| `fontfamily` | `{layer, font_style_id}` | Switch font for a text layer |
| `edit-style` | `{edit_style_id}` | Apply new layout preset, reset text colors + logo position |
| `regen-caption` | `{caption_tone}` | LLM regenerates headline/body/hashtags |
| `regen-image` | `{image_style, image_tier}` | AI regenerates background image |
| `regen-social` | `{caption_tone}` | LLM regenerates Instagram caption copy |
| `contact` | `{enabled, phone, email}` | Update contact bar layer |
| `export` (GET) | — | Copy composed.png to output/, serve as download |

Asset routes (`server/routes/assets.py`):
- `POST /api/session/{sid}/upload/{logo|header|footer|background}` — multipart file upload, normalized to RGBA PNG
- `DELETE /api/session/{sid}/upload/{type}` — removes file, clears `has_{type}` flag

---

## Session JSON structure (`src/core/session_manager.py`)

```jsonc
{
  "session_id": "abc12345",        // 8-char UUID slug
  "edit_style": "cinematic_overlay",
  "image_style": "...",            // legacy field (same as edit_style for new sessions)
  "image_type": "photo_lifestyle",
  "image_tier": "normal",          // normal | pro | max → selects Gemini model
  "palette_id": "neutral_elegant",
  "font_style": "sans_serif_bold",
  "industry": "lifestyle",
  "topic": "...",
  "caption_tone": "business_friendly",
  "brand_description": "...",
  "social_caption": "...",
  "has_logo": false,
  "has_header": false,
  "has_footer": false,
  "has_custom_bg": false,

  "headline_layer": { "text":"", "x":540, "y":280, "x_offset":0, "y_offset":0, "font_size":64, "color":"#FFF", "visible":true },
  "body_layer":     { "text":"", "x":540, "y":520, "x_offset":0, "y_offset":0, "font_size":30, "color":"#EEE", "visible":true },
  "hashtag_layer":  { "text":"", "x":540, "y":1230, "font_size":22, "color":"#AAA", "visible":true },
  "tag_layer":      { "text":"", "visible":true, "bg_color":"#B48C3C", "text_color":"#FFF", "font_size":26 },
  "logo_layer":     { "x":876, "y":44, "width":120, "height":120, "visible":true, "opacity":1.0, "position_override":false },
  "header_layer":   { "x":0, "y":0, "width":1080, "height":160, "visible":true, "opacity":1.0 },
  "footer_layer":   { "x":0, "y":1190, "width":1080, "height":160, "visible":true, "opacity":1.0 },
  "contact_bar_layer": { "enabled":false, "phone":"", "email":"", "bg_color":"#1a2e55", "text_color":"#FFF", "visible":true }
}
```

---

## Config system (`src/config/`)

All YAMLs loaded once at startup into `app.state.config` (see `server/main.py:load_config`).
Never read from disk in hot paths — always pass `cfg = request.app.state.config` through.

**edit_styles.yaml** — the most important config. Each style defines:
- `layout`: `full_bleed` or `split`
- `text_zone`: `top | middle | bottom | center | center_stack | band | matte | legacy`
  (`center_stack` vertically centers the measured text stack; `band`/`matte` anchor inside their zones)
- `overlay_type`: `gradient_top | gradient_bottom | gradient_left | solid | vignette | none`
- `logo_pos`: `top_right | top_left`
- `logo_max`: `[width, height]` max box the logo is scaled into
- `logo_padding`: distance from canvas edge
- `text_color_mode`: `white` (palette text colors) | `dark` (palette primary/secondary) | `white_pure` (#FFF — for text on brand-colored bands/duotones)

Premium design devices (category `premium`, all optional, full-bleed path only):
- `photo_treatment`: `duotone` (remaps photo to `duotone_dark`/`duotone_light`) | `mute` (desaturate+darken)
- `photo_matte`: photo inset on solid matte with drop shadow (`matte_padding`, `matte_bottom`, `matte_color`)
- `bottom_band_frac` / `bottom_band_color`: solid color block over the bottom of the photo
- `frame` / `frame_inset` / `frame_thickness` / `frame_color`: thin inner gallery border
- `text_backdrop`: `card` (solid rounded panel) | `glass` (blur + tint) with `backdrop_*` keys
- `kicker_style`: `pill | tracked` — eyebrow label above headline, text comes from `tag_layer`
- `headline_transform: uppercase`, `headline_tracking` (px letter-spacing), `text_shadow`
- `side_bar`: vertical accent bar beside left-aligned text; `quote_mark`: large decorative “
- Color values support palette refs: `"palette.accent"` (resolved by `_resolve_color`)

Split layouts (`layout: split`) use `_compose_split_layout()` which ignores most full-bleed settings. The split fraction is controlled by `photo_split` (0.0–1.0, fraction of height that is the photo zone).

Preview all styles without the server: `python -m tests.render_styles_smoke` → renders every style to `output/style_previews/`.

**color_palettes.yaml** — keys: `background`, `primary`, `secondary`, `text_primary`, `text_secondary`, `accent`, `gradient_end`. Palette colors are injected into both the image prompt and the composition.

**templates.yaml** — `font_styles` map: each entry has `headline_file`, `body_file` (font filenames in `static/fonts/`), plus `fallback_*` system font names.

---

## Editor UI (`src/templates/editor.html`)

Two-panel layout: left controls (294px), right preview.

**Layer tab system:** Headline / Body / Tags tabs update `data-layer` on all `.ctrl-block` buttons. Asset controls (logo/header/footer) are hardcoded per-asset.

**JS patterns:**
- All button actions use `data-action` / `data-layer` / `data-dx` etc. attributes.
- Single delegated `click` listener on `document` dispatches to `api()` helper.
- `api()` calls POST, gets `{ts}`, calls `refreshPreview(ts)` to cache-bust the `<img>`.
- Text edits debounced 600ms before firing `/text` endpoint.
- Asset uploads trigger `location.reload()` after 500ms (so new dpad/size controls appear).

**Font display:** `LAYER_FONTS` object tracks active font per layer; `updateFontPillsForLayer()` highlights the correct pill on tab switch.

---

## Image generation (`src/core/image_processor.py`)

Three quality tiers mapping to Gemini models via OpenRouter:
- `normal` → `google/gemini-2.5-flash-image`
- `pro` → `google/gemini-3.1-flash-image-preview`
- `max` → `google/gemini-3-pro-image-preview`

Response format: `choices[0].message.images[0].image_url.url` contains `data:image/png;base64,...`.
Falls back to `create_gradient_background()` (Pillow) if key missing or API fails.

Quality rules (`prompt_formatter.build_image_prompt`):
- Prompts are written as natural-language photographer briefs, not keyword soup. Photography types get `_PHOTO_REALISM` cues (full-frame camera, candid imperfection, "not digital art").
- `edit_cfg` must be passed in — its `text_zone` selects a `_COPY_SPACE` hint telling the model to leave clean negative space where text will be overlaid (top/middle/bottom/band/center/matte).
- Returned images are **cover-cropped** to 1080×1350 (`_resize_to`), never stretched — models often return square.
- Image type prompts live in `image_types.yaml`; avoid AI clichés ("8K", "ultra detailed") — they push models toward glossy digital-art looks. `_NO_TEXT` is appended centrally, don't repeat it per-type.

---

## Text generation (`src/core/text_generator.py`)

Uses OpenAI-compatible SDK pointed at `https://openrouter.ai/api/v1`.
Model: `OPENROUTER_TEXT_MODEL` env var, defaults to `deepseek/deepseek-chat`.
Returns `{headline, body, hashtags, social_caption}` JSON.
JSON parsed with regex fallback in case model wraps in markdown code fences.

---

## Font resolution order

1. `static/fonts/{filename}.ttf` (project fonts, committed to repo)
2. `C:/Windows/Fonts/` (Windows) or `/usr/share/fonts/` (Linux)
3. Pillow built-in default

Font filenames per style are in `templates.yaml` → `font_styles`.

---

## Key invariants

- Canvas is always **1080 × 1350** px (4:5 Instagram ratio).
- `compose_post()` is **synchronous** and has **no network calls** — safe to call on every keypress.
- Sessions are **8-char UUID slugs** stored as flat JSON files — no database.
- All uploaded assets are normalized to **RGBA PNG** on upload.
- Config is **never reloaded at runtime** — restart server to pick up YAML changes.
- `logo_layer.position_override = True` once the user manually moves the logo — disables preset positioning permanently for that session.
