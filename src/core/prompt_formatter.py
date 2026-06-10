from src.utils.logger import get_logger

log = get_logger(__name__)

INDUSTRY_LABELS = {
    "tech_innovation": "tech/software/AI",
    "wellness_health": "wellness/health/fitness",
    "fashion_beauty": "fashion/beauty/style",
    "food_beverage": "food/restaurant/cooking",
    "lifestyle": "lifestyle/travel/personal",
    "business_corporate": "business/corporate/B2B",
    "entertainment": "entertainment/gaming/music",
    "education_learning": "education/e-learning/tutorials",
    "personal_brand": "personal brand/influencer/creator",
    "ecommerce_promo": "ecommerce/promotion/products",
}

# Visual scene context per industry — tells the AI what to actually show
INDUSTRY_SCENE = {
    "tech_innovation": (
        "tech professionals collaborating, modern open-plan office with large monitors, "
        "clean desks, soft ambient lighting, people focused on screens"
    ),
    "wellness_health": (
        "person in peaceful natural setting, yoga, meditation or healthy lifestyle moment, "
        "soft morning light, green surroundings, sense of calm and vitality"
    ),
    "fashion_beauty": (
        "stylish model wearing fashionable clothing, editorial fashion photography, "
        "clean studio or lifestyle backdrop, elegant poses, premium styling"
    ),
    "food_beverage": (
        "beautifully plated dish or drink, restaurant or home kitchen setting, "
        "warm natural light, fresh ingredients artfully arranged, appetizing close-up"
    ),
    "lifestyle": (
        "real person enjoying an authentic lifestyle moment, travel destination or "
        "daily life scene, golden hour light, candid and warm"
    ),
    "business_corporate": (
        "confident professional in business setting, handshake or team meeting, "
        "modern boardroom or city skyline, sense of trust and success"
    ),
    "entertainment": (
        "vibrant entertainment scene, concert crowd, gaming setup or media event, "
        "dramatic stage lighting, energy and excitement"
    ),
    "education_learning": (
        "student or adult learner in bright study environment, books, laptop, "
        "focused expression, sense of growth and curiosity"
    ),
    "personal_brand": (
        "confident individual in authentic personal setting, candid portrait, "
        "creative workspace or lifestyle backdrop, approachable and genuine"
    ),
    "ecommerce_promo": (
        "product flat-lay or lifestyle product shot, clean background or real-world context, "
        "professional product photography, desirable and premium"
    ),
}

_NO_TEXT = (
    "no text, no words, no letters, no typography, no watermarks, "
    "no logos, no captions, no labels, no signs with writing"
)


_EXTENDED_JSON = (
    '\n\nReturn ONLY valid JSON with exactly these fields:\n'
    '{"headline": "short overlay headline for image (max 8 words)", '
    '"body": "supporting image body text (max 150 chars)", '
    '"social_caption": "standalone instagram caption in this same tone, 1-3 engaging sentences, no hashtags", '
    '"hashtags": ["#tag1","#tag2","#tag3","#tag4","#tag5","#tag6","#tag7",'
    '"#tag8","#tag9","#tag10","#tag11","#tag12","#tag13"]}'
)


def build_brand_analysis_prompt(
    description: str,
    topic: str,
    industries: list,
    image_types: list,
    edit_styles: list,
    caption_tones: list,
    palettes: list,
    font_styles: list,
) -> str:
    topic_line = f"\nPost topic: {topic}" if topic.strip() else ""
    return (
        f"Analyze this brand/product and choose the best Instagram post settings.\n\n"
        f"Brand description: {description}{topic_line}\n\n"
        f"Pick exactly one value from each list below:\n"
        f"industry: {', '.join(industries)}\n"
        f"image_type: {', '.join(image_types)}\n"
        f"edit_style: {', '.join(edit_styles)}\n"
        f"caption_tone: {', '.join(caption_tones)}\n"
        f"palette_id: {', '.join(palettes)}\n"
        f"font_style: {', '.join(font_styles)}\n\n"
        f"Return ONLY valid JSON:\n"
        f'{{"industry":"...","image_type":"...","edit_style":"...","caption_tone":"...","palette_id":"...","font_style":"..."}}'
    )


def build_caption_prompt(topic: str, tone_config: dict, industry: str, brand_context: str = "") -> str:
    label = INDUSTRY_LABELS.get(industry, industry)
    template = tone_config.get("llm_prompt", "")
    base = template.format(topic=topic, industry=label)
    # Strip the old short JSON format line from the prompt and inject the extended one
    lines = base.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip().startswith("{"):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and "Return ONLY valid JSON" in lines[-1]:
        lines.pop()
    brand_part = f"Brand context: {brand_context.strip()}\n\n" if brand_context.strip() else ""
    return brand_part + "\n".join(lines) + _EXTENDED_JSON


def build_social_prompt(topic: str, tone_config: dict, industry: str) -> str:
    label = INDUSTRY_LABELS.get(industry, industry)
    tone_name = tone_config.get("name", "engaging")
    return (
        f"Write a {tone_name} Instagram caption and hashtags for: {topic}\n"
        f"Industry: {label}\n\n"
        "Return ONLY valid JSON:\n"
        '{"social_caption": "standalone instagram caption in this tone, 1-3 engaging sentences, no hashtags", '
        '"hashtags": ["#tag1","#tag2","#tag3","#tag4","#tag5","#tag6","#tag7",'
        '"#tag8","#tag9","#tag10","#tag11","#tag12","#tag13"]}'
    )


# Copy-space direction per edit-style text zone — tells the model to leave
# clean negative space where the headline/body will be overlaid, the way an
# art director briefs a photographer for a layout.
_COPY_SPACE = {
    "top": (
        "Compose with the upper third of the frame clean and uncluttered "
        "(open sky, plain wall, or soft out-of-focus area) — headline text will be "
        "placed there. Keep the main subject in the lower two thirds."
    ),
    "middle": (
        "Keep the middle band of the frame visually calm and free of busy detail "
        "so overlaid text stays readable; place key subject interest toward the "
        "lower half or the edges of the frame."
    ),
    "bottom": (
        "Compose with the lower third of the frame simple and free of busy detail — "
        "text will be placed there. Keep the main subject in the upper two thirds."
    ),
    "band": (
        "Compose with the lower third simple — it will be covered by a solid color "
        "panel. Keep the main subject and all interest in the upper two thirds."
    ),
    "center": (
        "Frame the main subject slightly off-center and keep the center of the "
        "frame relatively calm — text will be overlaid in the middle."
    ),
    "center_stack": (
        "Frame the main subject slightly off-center and keep the center of the "
        "frame relatively calm — text will be overlaid in the middle."
    ),
    "matte": (
        "Center the main subject with comfortable margins on every side — the "
        "photo will be cropped into a matte frame."
    ),
}

# Realism cues for photography types — pushes the model away from the glossy
# over-perfect digital-art look toward believable campaign photography.
_PHOTO_REALISM = (
    "Shot on a professional full-frame camera with a fast prime lens. "
    "Natural realistic lighting, true-to-life colors and skin texture, honest "
    "candid feel with small real-world imperfections, subtle fine grain — it must "
    "look like an actual photograph from a brand campaign, not digital art. "
)


def build_image_prompt(
    topic: str,
    image_type_cfg: dict,
    palette: dict,
    industry: str = "",
    edit_cfg: dict | None = None,
) -> str:
    """Build AI image generation prompt from image_type_cfg (new) or legacy style_config.
    edit_cfg (the post layout) drives copy-space composition hints."""
    scene           = INDUSTRY_SCENE.get(industry, "professional lifestyle photography scene")
    base_prompt     = image_type_cfg.get("prompt", image_type_cfg.get("image_prompt", ""))
    photo_direction = image_type_cfg.get("photo_direction", "")
    use_palette     = image_type_cfg.get("use_palette", True)
    is_photo        = image_type_cfg.get("category", "") == "photography"

    # Split layouts: photo fills the bottom zone only — no text lands on it
    if (edit_cfg or {}).get("layout") == "split" or image_type_cfg.get("layout") == "split":
        return (
            f"A vertical portrait-format photograph about {topic}. "
            f"Scene: {scene}. "
            f"{_PHOTO_REALISM}"
            f"Cinematic composition with the main subject centered. {_NO_TEXT}."
        )

    direction_part = f"Photography direction: {photo_direction}. " if photo_direction else ""
    realism_part   = _PHOTO_REALISM if is_photo else ""

    text_zone  = (edit_cfg or {}).get("text_zone", "")
    copy_space = _COPY_SPACE.get(text_zone, "")
    if copy_space:
        copy_space += " "

    if use_palette:
        primary   = palette.get("primary",   "#FFFFFF")
        secondary = palette.get("secondary", "#000000")
        palette_part = f"Color palette built around {primary} and {secondary}. "
    else:
        palette_part = ""

    kind = "photograph" if is_photo else "image"
    return (
        f"A vertical 4:5 portrait-format {kind} for an Instagram post about {topic}. "
        f"Scene: {scene}. "
        f"Style: {base_prompt}. "
        f"{direction_part}"
        f"{realism_part}"
        f"{copy_space}"
        f"{palette_part}"
        f"{_NO_TEXT}."
    )
