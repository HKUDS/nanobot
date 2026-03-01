"""Multi-model provider with fallback support."""

from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.providers.custom_provider import CustomProvider
from nanobot.config.schema import Config
from nanobot.providers.registry import find_by_name


class MultiModelProvider(LLMProvider):
    """
    LLM provider that supports multiple models with automatic fallback.

    When a model call fails, it automatically retries with the next model
    in the list until all models have been tried.
    """

    def __init__(
        self,
        config: Config,
        models: list[str] | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
    ):
        """
        Initialize the multi-model provider.

        Args:
            config: The nanobot configuration.
            models: List of model identifiers to try in order. If None or empty,
                    uses the single default_model.
            default_model: Default model to use if models list is empty.
        """
        self.config = config
        self.models = models or [default_model]
        self.default_model = default_model
        self._providers: dict[str, LLMProvider] = {}

    def _get_provider_for_model(self, model: str) -> LLMProvider:
        """Get or create a provider for the given model."""
        if model not in self._providers:
            provider_config = self.config.get_provider(model)
            provider_name = self.config.get_provider_name(model)
            spec = find_by_name(provider_name) if provider_name else None

            # OpenAI Codex (OAuth)
            if provider_name == "openai_codex" or model.startswith("openai-codex/"):
                self._providers[model] = OpenAICodexProvider(default_model=model)
            # Custom: direct OpenAI-compatible endpoint
            elif provider_name == "custom":
                self._providers[model] = CustomProvider(
                    api_key=provider_config.api_key if provider_config else "no-key",
                    api_base=self.config.get_api_base(model) or "http://localhost:8000/v1",
                    default_model=model,
                )
            # Standard LiteLLM provider
            else:
                self._providers[model] = LiteLLMProvider(
                    api_key=provider_config.api_key if provider_config else None,
                    api_base=provider_config.api_base if provider_config else None,
                    default_model=model,
                    extra_headers=provider_config.extra_headers if provider_config else None,
                    provider_name=provider_name,
                )

        return self._providers[model]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request with automatic model fallback.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (if provided, this model is tried first, followed by others in case of failure).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        # Determine the order of models to try
        # If a specific model is requested, try it first, then other models
        # If no specific model is requested, try models in configured order
        if model:
            # Put the requested model first, then other models
            models_to_try = [model]
            for m in self.models:
                if m != model:
                    models_to_try.append(m)
        else:
            # Use configured models order
            models_to_try = self.models

        last_error = None
        errors: list[tuple[str, str]] = []

        for idx, model_name in enumerate(models_to_try):
            try:
                provider = self._get_provider_for_model(model_name)

                logger.debug("Trying model {}: {}", idx + 1, model_name)
                response = await provider.chat(
                    messages=messages,
                    tools=tools,
                    model=model_name,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                # Check if response indicates an error
                if response.finish_reason == "error" or (
                    response.content and response.content.startswith("Error calling LLM:")
                ):
                    error_msg = response.content or "Unknown error"
                    logger.warning("Model {} failed: {}", model_name, error_msg)
                    errors.append((model_name, error_msg))
                    last_error = Exception(error_msg)
                    continue

                # Success - log which model succeeded if we tried multiple
                if len(models_to_try) > 1 and idx > 0:
                    logger.info("Model fallback succeeded: {} -> {}", models_to_try[0], model_name)

                return response

            except Exception as e:
                logger.warning("Model {} threw exception: {}", model_name, str(e))
                errors.append((model_name, str(e)))
                last_error = e
                continue

        # All models failed
        error_summary = "; ".join(f"{m}: {e[:50]}..." if len(e) > 50 else f"{m}: {e}" for m, e in errors)
        logger.error("All models failed: {}", error_summary)

        # Return an error response instead of raising
        return LLMResponse(
            content=f"Error: All models failed. {error_summary}",
            finish_reason="error",
        )

    def get_default_model(self) -> str:
        """Get the first model in the list as the default."""
        return self.models[0] if self.models else self.default_model

    def get_models(self) -> list[str]:
        """Get the list of models."""
        return self.models.copy()
