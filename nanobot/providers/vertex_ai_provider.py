"""Anthropic Claude provider for Google Vertex AI."""

from __future__ import annotations

import os
from typing import Any

from nanobot.providers.anthropic_provider import AnthropicProvider


class VertexAIProvider(AnthropicProvider):
    """Use Anthropic's Messages API through Google Vertex AI."""

    def __init__(
        self,
        default_model: str = "claude-sonnet-4-5@20250929",
        project: str | None = None,
        region: str | None = None,
        *,
        provider_name: str = "google_vertex_ai",
    ) -> None:
        self.project = project or os.getenv("ANTHROPIC_VERTEX_PROJECT_ID") or os.getenv(
            "GOOGLE_CLOUD_PROJECT"
        )
        self.region = region or os.getenv("CLOUD_ML_REGION") or os.getenv(
            "GOOGLE_CLOUD_LOCATION"
        ) or "us-central1"
        super().__init__(
            default_model=default_model,
            provider_name=provider_name,
        )

    def _create_client(
        self,
        api_key: str | None,
        api_base: str | None,
        extra_headers: dict[str, str] | None,
    ) -> Any:
        try:
            from anthropic.lib.vertex import AsyncAnthropicVertex

            client_kw: dict[str, Any] = {
                "region": self.region,
                "max_retries": 0,
            }
            if self.project:
                client_kw["project_id"] = self.project
            return AsyncAnthropicVertex(**client_kw)
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "Google Vertex AI support requires the 'vertex' extra: "
                "pip install 'nanobot-ai[vertex]'"
            ) from exc

    @staticmethod
    def _strip_prefix(model: str) -> str:
        for prefix in ("google_vertex_ai/", "vertex_ai/", "vertex/", "anthropic/"):
            if model.startswith(prefix):
                return model[len(prefix):]
        return model
