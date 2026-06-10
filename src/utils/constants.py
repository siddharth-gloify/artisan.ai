from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
SRC_DIR = BASE_DIR / "src"
STATIC_DIR = BASE_DIR / "static"
STORAGE_DIR = SRC_DIR / "storage"
SESSIONS_DIR = STORAGE_DIR / "sessions"
OUTPUTS_DIR = STORAGE_DIR / "outputs"
CONFIG_DIR = SRC_DIR / "config"
FONTS_DIR = STATIC_DIR / "fonts"

# Root-level output folder — every finished post lands here
OUTPUT_DIR = BASE_DIR / "output"

POST_WIDTH = 1080
POST_HEIGHT = 1350

DEFAULT_FONT_SIZE_HEADLINE = 64
DEFAULT_FONT_SIZE_BODY = 30
DEFAULT_FONT_SIZE_HASHTAG = 22

TEXT_PADDING = 80
MAX_TEXT_WIDTH = POST_WIDTH - (TEXT_PADDING * 2)

WINDOWS_FONT_DIR = Path("C:/Windows/Fonts")
LINUX_FONT_DIRS = [
    Path("/usr/share/fonts/truetype"),
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
]

IMAGE_PROVIDERS = ["fal", "replicate", "openai", "none"]
LLM_PROVIDERS = ["anthropic", "openai", "none"]
