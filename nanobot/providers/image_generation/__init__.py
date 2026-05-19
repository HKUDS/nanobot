"""Image generation providers — per-provider modules with auto-discovery."""

from nanobot.providers.image_generation.aihubmix import AIHubMixImageGenerationClient
from nanobot.providers.image_generation.base import (
    GeneratedImageResponse,
    ImageGenerationError,
    ImageGenerationProvider,
    image_path_to_data_url,
)
from nanobot.providers.image_generation.gemini import (
    GeminiImageGenerationClient,
    image_path_to_inline_data,
)
from nanobot.providers.image_generation.minimax import MiniMaxImageGenerationClient
from nanobot.providers.image_generation.openrouter import OpenRouterImageGenerationClient
from nanobot.providers.image_generation.registry import (
    get_image_gen_provider,
    image_gen_provider_configs,
    image_gen_provider_names,
    register_image_gen_provider,
)

__all__ = [
    "AIHubMixImageGenerationClient",
    "GeminiImageGenerationClient",
    "GeneratedImageResponse",
    "ImageGenerationError",
    "ImageGenerationProvider",
    "MiniMaxImageGenerationClient",
    "OpenRouterImageGenerationClient",
    "get_image_gen_provider",
    "image_gen_provider_configs",
    "image_gen_provider_names",
    "image_path_to_data_url",
    "image_path_to_inline_data",
    "register_image_gen_provider",
]
