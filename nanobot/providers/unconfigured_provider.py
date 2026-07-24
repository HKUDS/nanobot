"""Provider used while the local WebUI is waiting for first-time setup."""

from __future__ import annotations

from nanobot.providers.base import LLMProvider, LLMResponse


class UnconfiguredProvider(LLMProvider):
    """Keep the gateway available for settings before a model is configured."""

    def __init__(self, default_model: str) -> None:
        super().__init__()
        self._default_model = default_model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content=(
                "Nanobot needs a model before it can chat. Open Settings → Models "
                "to configure a provider and model, then send your message again."
            ),
            finish_reason="error",
            error_kind="configuration",
            error_should_retry=False,
        )

    def get_default_model(self) -> str:
        return self._default_model
