"""Image generation configuration shared by the tool and root schema."""

from typing import Any

from pydantic import Field

from nanobot.config_base import Base


class ImageGenerationToolConfig(Base):
    """Image generation tool configuration."""
    enabled: bool = False
    provider: str = "openrouter"
    model: str = "openai/gpt-5.4-image-2"
    default_aspect_ratio: str = "1:1"
    default_image_size: str = "1K"
    max_images_per_turn: int = Field(default=4, ge=1, le=8)
    save_dir: str = "generated"
    extra_headers: dict[str, str] | None = Field(default=None, repr=False)
    extra_body: dict[str, Any] | None = Field(default=None, repr=False)
