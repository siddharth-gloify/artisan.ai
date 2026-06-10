from fastapi import HTTPException


def validate_image_style(style_id: str, config: dict) -> dict:
    styles = config.get("image_styles", {})
    if style_id not in styles:
        raise HTTPException(400, f"Unknown image style: {style_id}")
    return styles[style_id]


def validate_palette(palette_id: str, config: dict) -> dict:
    palettes = config.get("color_palettes", {})
    if palette_id not in palettes:
        raise HTTPException(400, f"Unknown palette: {palette_id}")
    return palettes[palette_id]


def validate_tone(tone_id: str, config: dict) -> dict:
    tones = config.get("caption_tones", {})
    if tone_id not in tones:
        raise HTTPException(400, f"Unknown tone: {tone_id}")
    return tones[tone_id]
