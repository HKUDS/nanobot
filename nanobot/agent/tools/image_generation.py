"""Image generation tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import Field

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config.paths import get_media_dir
from nanobot.config_base import Base
from nanobot.providers.image_generation import (
    ImageGenerationError,
    ImageGenerationProvider,
    get_image_gen_provider,
)
from nanobot.security.workspace_access import current_tool_workspace
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path
from nanobot.utils.artifacts import (
    ArtifactError,
    generated_image_tool_result,
    store_generated_image_artifact,
)
from nanobot.utils.helpers import detect_image_mime

if TYPE_CHECKING:
    from nanobot.config.schema import ProviderConfig


class ImageGenerationToolConfig(Base):
    """Image generation tool configuration."""
    enabled: bool = False
    provider: str = "openrouter"
    model: str = "openai/gpt-5.4-image-2"
    default_aspect_ratio: str = "1:1"
    default_image_size: str = "1K"
    max_images_per_turn: int = Field(default=4, ge=1, le=8)
    save_dir: str = "generated"


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
        model=StringSchema(
            "Optional per-call model override. If specified, uses this model instead of the configured default. Use 'gpt-image-2' only for complex scenes, human faces, in-image text, or high-precision requirements.",
        ),
        required=["prompt"],
    )
)
class ImageGenerationTool(Tool):
    """Generate persistent image artifacts through the configured image provider."""

    config_key = "image_generation"

    @classmethod
    def config_cls(cls):
        return ImageGenerationToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.image_generation.enabled

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(
            workspace=ctx.workspace,
            config=ctx.config.image_generation,
            provider_configs=ctx.image_generation_provider_configs,
        )

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

    def _provider_client(self) -> ImageGenerationProvider | None:
        provider = self._provider_config()
        cls = get_image_gen_provider(self.config.provider)
        if cls is None:
            return None
        kwargs = {
            "api_key": provider.api_key if provider else None,
            "api_base": provider.api_base if provider else None,
            "extra_headers": provider.extra_headers if provider else None,
            "extra_body": provider.extra_body if provider else None,
            "proxy": provider.proxy if provider else None,
        }
        return cls(**kwargs)

    def _resolve_reference_image(self, value: str) -> str:
        access = current_tool_workspace(self.workspace, restrict_to_workspace=True)
        workspace = access.project_path or self.workspace
        try:
            resolved = resolve_allowed_path(
                value,
                workspace=workspace,
                allowed_root=access.allowed_root,
                extra_allowed_roots=[get_media_dir()] if access.allowed_root is not None else None,
                strict=True,
            )
        except WorkspaceBoundaryError as exc:
            raise ImageGenerationError(
                "reference_images must be inside the workspace or nanobot media directory"
            ) from exc
        except OSError as exc:
            raise ImageGenerationError(f"reference image not found: {value}") from exc
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
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        client = self._provider_client()
        if client is None:
            return ToolResult.error(f"Error: unsupported image generation provider '{self.config.provider}'")

        requested = count or 1
        if requested > self.config.max_images_per_turn:
            return ToolResult.error(
                "Error: count exceeds tools.imageGeneration.maxImagesPerTurn "
                f"({self.config.max_images_per_turn})"
            )

        allowed_models = {"gemini-2.5-flash-image", "gpt-image-2", "gpt-image-1", "dall-e-3"}
        if model and model not in allowed_models:
            return ToolResult.error(
                f"Error: unsupported model '{model}'. "
                f"Allowed models: {', '.join(sorted(allowed_models))}"
            )

        if model:
            effective_model = model
        else:
            effective_model = self._select_model(prompt)

        try:
            refs = self._resolve_reference_images(reference_images)
            artifacts: list[dict[str, Any]] = []
            while len(artifacts) < requested:
                response = await self._generate_with_retry(
                    client, prompt, effective_model, refs,
                    aspect_ratio or self.config.default_aspect_ratio,
                    image_size or self.config.default_image_size,
                )
                for image_data_url in response.images:
                    artifact = store_generated_image_artifact(
                        image_data_url,
                        prompt=prompt,
                        model=effective_model,
                        source_images=refs,
                        save_dir=self.config.save_dir,
                        provider=self.config.provider,
                    )
                    artifacts.append(artifact)
                    if len(artifacts) >= requested:
                        break
            return generated_image_tool_result(artifacts)
        except (ArtifactError, ImageGenerationError, OSError) as exc:
            return ToolResult.error(f"Error: {exc}")

    @staticmethod
    def _select_model(prompt: str) -> str:
        """根据 prompt 特征自动选择模型。

        人像 / 图内文字 / 复杂场景 → gpt-image-2；
        其他 → 默认便宜档。

        关键词经过收紧，避免误升档浪费费用。
        """
        prompt_lower = prompt.lower()

        # 人像 / 人脸检测（必须是明确的人像意图）
        portrait_keywords = [
            "portrait", "portraits",
            "selfie", "selfies",
            "headshot", "headshots",
            "profile photo", "profile picture",
            "人像", "肖像", "自拍",
            "证件照", "头像照",
        ]
        for kw in portrait_keywords:
            if kw in prompt_lower:
                return "gpt-image-2"

        # 图内文字检测（必须有明确的"文字出现在图中"意图）
        text_in_image_keywords = [
            "sign that says", "sign reading", "sign with",
            "banner that says", "poster with text",
            "label that reads", "text that says",
            "writing on the", "written on the",
            "写着", "牌子", "标语", "横幅",
            "文字", "字母",
        ]
        for kw in text_in_image_keywords:
            if kw in prompt_lower:
                return "gpt-image-2"

        # 高精度 / 写实检测（必须是明确的写实风格要求）
        quality_keywords = [
            "photorealistic", "hyperrealistic", "realistic photo",
            "cinematic photo", "dslr", "8k render",
            "写实风", "超写实", "电影级",
        ]
        for kw in quality_keywords:
            if kw in prompt_lower:
                return "gpt-image-2"

        return "gemini-2.5-flash-image"

    async def _generate_with_retry(
        self,
        client: Any,
        prompt: str,
        model: str,
        reference_images: list[str],
        aspect_ratio: str,
        image_size: str,
    ) -> Any:
        """调用生图 API，瞬时失败自动重试 1 次（同 model）。"""
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                return await client.generate(
                    prompt=prompt,
                    model=model,
                    reference_images=reference_images,
                    aspect_ratio=aspect_ratio,
                    image_size=image_size,
                )
            except (ImageGenerationError, OSError) as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status and 400 <= status < 500:
                    raise
                if attempt == 0:
                    logger.warning(
                        "Image generation failed (attempt 1/2, model={}): {}. Retrying...",
                        model, exc,
                    )
                    continue
        raise last_exc  # type: ignore[misc]
