from typing import Literal

from server.app_deps import Field
from server.modules.request_model import StrictRequestModel


class ImagePromptPreferences(StrictRequestModel):
    output_language: Literal["english", "japanese"] = "english"
    subject: str = Field(default="", max_length=300)
    hair_color: str = Field(default="", max_length=80)
    secondary_hair_color_enabled: bool = False
    secondary_hair_color: str = Field(default="", max_length=80)
    secondary_hair_color_style: str = Field(default="", max_length=300)
    eye_color: str = Field(default="", max_length=80)
    eye_style: str = Field(default="", max_length=300)
    hair_length: str = Field(default="", max_length=300)
    hairstyle: str = Field(default="", max_length=300)
    expression: str = Field(default="", max_length=300)
    outfit: str = Field(default="", max_length=600)
    outfit_impression: str = Field(default="", max_length=300)
    occupation: str = Field(default="", max_length=300)
    accessory: str = Field(default="", max_length=600)
    style: str = Field(default="", max_length=300)
    composition: str = Field(default="", max_length=300)
    screen_effect: str = Field(default="", max_length=300)
    background: str = Field(default="", max_length=600)
    skin_tone: str = Field(default="", max_length=300)
    hair_texture: str = Field(default="", max_length=300)
    bangs: str = Field(default="", max_length=300)
    facial_hair: str = Field(default="", max_length=300)
    body_build: str = Field(default="", max_length=300)
    age_impression: str = Field(default="", max_length=300)
    face_contour: str = Field(default="", max_length=300)
    eyebrow_shape: str = Field(default="", max_length=300)
    makeup: str = Field(default="", max_length=300)
    height: str = Field(default="", max_length=300)
    bust_size: str = Field(default="", max_length=300)
    freckles_moles: str = Field(default="", max_length=600)
    scars: str = Field(default="", max_length=600)
    tattoos: str = Field(default="", max_length=600)
    pose: str = Field(default="", max_length=300)
    gestures: list[str] = Field(default_factory=list, max_length=20)
    camera_angle: str = Field(default="", max_length=300)
    background_color: str = Field(default="", max_length=80)
    background_gradient_color1: str = Field(default="", max_length=80)
    background_gradient_color2: str = Field(default="", max_length=80)
    background_gradient_direction: str = Field(default="", max_length=300)
    request: str = Field(default="", max_length=3000)
