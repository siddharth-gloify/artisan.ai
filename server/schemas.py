from pydantic import BaseModel, Field
from typing import Optional


class GenerateRequest(BaseModel):
    industry: str
    image_style: str
    caption_tone: str
    palette_id: str
    font_style: str
    topic: str


class TextLayerEdit(BaseModel):
    text: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    font_size: Optional[int] = None
    color: Optional[str] = None
    visible: Optional[bool] = None


class AssetLayerEdit(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    visible: Optional[bool] = None
    opacity: Optional[float] = None


class EditRequest(BaseModel):
    headline_layer: Optional[TextLayerEdit] = None
    body_layer: Optional[TextLayerEdit] = None
    hashtag_layer: Optional[TextLayerEdit] = None
    logo_layer: Optional[AssetLayerEdit] = None
    header_layer: Optional[AssetLayerEdit] = None
    footer_layer: Optional[AssetLayerEdit] = None
    recompose: bool = True


class MoveRequest(BaseModel):
    layer: str   # "headline" | "body" | "hashtag" | "logo" | "header" | "footer"
    dx: int = 0
    dy: int = 0


class FontSizeRequest(BaseModel):
    layer: str   # "headline" | "body" | "hashtag"
    delta: int   # +2 or -2


class ColorRequest(BaseModel):
    layer: str   # "headline" | "body" | "hashtag"
    color: str   # hex


class RegenerateCaption(BaseModel):
    topic: Optional[str] = None
    caption_tone: Optional[str] = None
