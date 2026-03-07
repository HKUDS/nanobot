"""LiteLLM Router subclass with OpenCode Zen support."""

from typing import Any, Optional
from openai import AsyncOpenAI
from litellm import Router
from loguru import logger


class OpenCodeRouter(Router):
    """Extended Router that handles OpenCode Zen's empty API key requirement."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._opencode_clients: dict[str, AsyncOpenAI] = {}

    async def acompletion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Override acompletion to handle OpenCode Zen specially."""
        # Check if this is an OpenCode Zen request
        is_opencode = (
            model.startswith("opencode/")
            or model.startswith("hosted_vllm/")
            or (api_base and "opencode.ai" in api_base)
        )

        if is_opencode and api_key == "":
            # Handle OpenCode Zen with empty API key
            return await self._opencode_completion(
                model=model, messages=messages, api_base=api_base, **kwargs
            )

        # Not OpenCode or has API key, use normal flow
        return await super().acompletion(
            model=model, messages=messages, api_base=api_base, api_key=api_key, **kwargs
        )

    async def _opencode_completion(
        self, model: str, messages: list[dict[str, Any]], api_base: Optional[str] = None, **kwargs
    ) -> Any:
        """Handle OpenCode Zen completion with empty API key."""
        # Extract model name
        if model.startswith("opencode/"):
            model_name = model.replace("opencode/", "")
        elif model.startswith("hosted_vllm/"):
            model_name = model.replace("hosted_vllm/", "")
        else:
            model_name = model

        base_url = api_base or "https://opencode.ai/zen/v1"
        client_key = f"{base_url}:{model_name}"

        # Get or create OpenAI client with empty API key
        if client_key not in self._opencode_clients:
            self._opencode_clients[client_key] = AsyncOpenAI(
                api_key="",  # Empty string for OpenCode
                base_url=base_url,
            )

        client = self._opencode_clients[client_key]

        # Make the request
        try:
            response = await client.chat.completions.create(
                model=model_name, messages=messages, **kwargs
            )
            return response
        except Exception as e:
            logger.error(f"OpenCode Zen error: {e}")
            raise
