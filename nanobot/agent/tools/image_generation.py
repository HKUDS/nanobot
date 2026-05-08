"""Image generation tool."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import ImageGenerationToolConfig
from nanobot.providers.image_generation import (
    AIHubMixImageGenerationClient,
    ImageGenerationError,
    OpenRouterImageGenerationClient,
)
from nanobot.utils.artifacts import (
    ArtifactError,
    generated_image_tool_result,
    store_generated_image_artifact,
)
from nanobot.utils.helpers import detect_image_mime

if TYPE_CHECKING:
    from nanobot.config.schema import ProviderConfig


@tool_parameters(
    tool_parameters_schema(
        prompt=StringSchema(
            "Detailed image generation or edit prompt. Include style, subject, composition, colors, and constraints.",
            min_length=1,
        ),
        reference_images=ArraySchema(
            StringSchema("Local path of an existing image artifact or user-provided image to use as an edit reference."),
            description="Optional local image paths. Use generated artifact paths for iterative edits.",
        ),
        aspect_ratio=StringSchema(
            "Optional output aspect ratio, e.g. 1:1, 16:9, 9:16, 4:3.",
        ),
        image_size=StringSchema(
            "Optional output size hint supported by the configured provider, e.g. 1K, 2K, 4K, or 1024x1024.",
        ),
        count=IntegerSchema(
            description="Number of images to generate in this turn.",
            minimum=1,
            maximum=8,
        ),
        required=["prompt"],
    )
)
class ImageGenerationTool(Tool):
    """Generate persistent image artifacts through the configured image provider."""

    def __init__(
        self,
        *,
        workspace: str | Path,
        config: ImageGenerationToolConfig,
        provider_config: ProviderConfig | None = None,
        provider_configs: dict[str, ProviderConfig] | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser()
        self.config = config
        self.provider_configs = dict(provider_configs or {})
        if provider_config is not None and "openrouter" not in self.provider_configs:
            self.provider_configs["openrouter"] = provider_config

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return (
            "Generate or edit images and store them as persistent artifacts. "
            "Returns artifact ids and local paths. For edits, pass prior generated image paths "
            "or user image paths as reference_images."
        )

    def _provider_config(self) -> ProviderConfig | None:
        return self.provider_configs.get(self.config.provider)

    def _provider_client(self) -> OpenRouterImageGenerationClient | AIHubMixImageGenerationClient | None:
        provider = self._provider_config()
        kwargs = {
            "api_key": provider.api_key if provider else None,
            "api_base": provider.api_base if provider else None,
            "extra_headers": provider.extra_headers if provider else None,
            "extra_body": provider.extra_body if provider else None,
        }
        if self.config.provider == "openrouter":
            return OpenRouterImageGenerationClient(**kwargs)
        if self.config.provider == "aihubmix":
            return AIHubMixImageGenerationClient(**kwargs)
        return None

    def _missing_api_key_error(self) -> str:
        provider = self.config.provider
        if provider == "openrouter":
            return "Error: OpenRouter API key is not configured. Set providers.openrouter.apiKey."
        if provider == "aihubmix":
            return "Error: AIHubMix API key is not configured. Set providers.aihubmix.apiKey."
        return f"Error: {provider} API key is not configured."

    def _resolve_reference_image(self, value: str) -> str:
        raw_path = Path(value).expanduser()
        path = raw_path if raw_path.is_absolute() else self.workspace / raw_path
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ImageGenerationError(f"reference image not found: {value}") from exc

        allowed_roots = [self.workspace.resolve(), get_media_dir().resolve()]
        if not any(_is_relative_to(resolved, root) for root in allowed_roots):
            raise ImageGenerationError(
                "reference_images must be inside the workspace or nanobot media directory"
            )
        if not resolved.is_file():
            raise ImageGenerationError(f"reference image is not a file: {value}")
        raw = resolved.read_bytes()
        if detect_image_mime(raw) is None:
            raise ImageGenerationError(f"unsupported reference image: {value}")
        return str(resolved)

    def _resolve_reference_images(self, values: list[str] | None) -> list[str]:
        if not values:
            return []
        return [self._resolve_reference_image(value) for value in values if value]

    async def execute(
        self,
        prompt: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
        count: int | None = None,
        **kwargs: Any,
    ) -> str:
        client = self._provider_client()
        if client is None:
            return f"Error: unsupported image generation provider '{self.config.provider}'"
        provider = self._provider_config()
        if not provider or not provider.api_key:
            return self._missing_api_key_error()

        requested = count or 1
        if requested > self.config.max_images_per_turn:
            return (
                "Error: count exceeds tools.imageGeneration.maxImagesPerTurn "
                f"({self.config.max_images_per_turn})"
            )

        try:
            refs = self._resolve_reference_images(reference_images)
            artifacts: list[dict[str, Any]] = []
            while len(artifacts) < requested:
                response = await client.generate(
                    prompt=prompt,
                    model=self.config.model,
                    reference_images=refs,
                    aspect_ratio=aspect_ratio or self.config.default_aspect_ratio,
                    image_size=image_size or self.config.default_image_size,
                )
                for image_data_url in response.images:
                    artifact = store_generated_image_artifact(
                        image_data_url,
                        prompt=prompt,
                        model=self.config.model,
                        source_images=refs,
                        save_dir=self.config.save_dir,
                        provider=self.config.provider,
                    )
                    artifacts.append(artifact)
                    if len(artifacts) >= requested:
                        break
            return generated_image_tool_result(artifacts)
        except (ArtifactError, ImageGenerationError, OSError) as exc:
            return f"Error: {exc}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
