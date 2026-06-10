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


def build_caption_prompt(topic: str, tone_config: dict, industry: str) -> str:
    label = INDUSTRY_LABELS.get(industry, industry)
    template = tone_config.get("llm_prompt", "")
    return template.format(topic=topic, industry=label)


def build_image_prompt(topic: str, style_config: dict, palette: dict, industry: str = "") -> str:
    scene = INDUSTRY_SCENE.get(industry, "professional lifestyle photography scene")
    style_aesthetic = style_config.get("image_prompt", "")

    if style_config.get("layout") == "split":
        # Pure photographic scene — topic + industry context drives what's shown
        return (
            f"Photorealistic photograph about {topic}. "
            f"Show: {scene}. "
            f"Cinematic composition, ultra detailed, 8K, {_NO_TEXT}."
        )

    primary = palette.get("primary", "#FFFFFF")
    secondary = palette.get("secondary", "#000000")
    return (
        f"Photorealistic image about {topic}. "
        f"Show: {scene}. "
        f"Visual style: {style_aesthetic}. "
        f"Color palette featuring {primary} and {secondary}. "
        f"Instagram post format 4:5, high quality, professional, {_NO_TEXT}."
    )
