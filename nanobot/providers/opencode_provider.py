"""OpenCode Zen provider for LiteLLM.

This provider handles OpenCode Zen's unique requirement of empty API keys for free models.
"""

from typing import Any, Optional, Union, Callable
import httpx
from openai import AsyncOpenAI
from loguru import logger

from litellm.llms.custom_llm import CustomLLM, CustomLLMError
from litellm.types.utils import ModelResponse


class OpenCodeProvider(CustomLLM):
    """OpenCode Zen provider that handles empty API keys."""

    def __init__(self):
        super().__init__()
        self._clients: dict[str, AsyncOpenAI] = {}

    def _get_client(self, api_base: str, api_key: Optional[str]) -> AsyncOpenAI:
        """Get or create OpenAI client for OpenCode Zen.

        OpenCode Zen requires empty API key, but OpenAI SDK requires non-empty.
        We handle this by using httpx directly with custom headers.
        """
        client_key = f"{api_base}:{api_key or 'empty'}"

        if client_key not in self._clients:
            # For OpenCode Zen, we create a custom client that doesn't send Authorization header
            # when api_key is empty
            if api_key == "" or api_key is None:
                # Create client without default auth
                self._clients[client_key] = AsyncOpenAI(
                    api_key="opencode-placeholder",  # Placeholder, we'll override headers
                    base_url=api_base,
                )
            else:
                self._clients[client_key] = AsyncOpenAI(
                    api_key=api_key,
                    base_url=api_base,
                )

        return self._clients[client_key]

    async def acompletion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers={},
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client=None,
    ) -> ModelResponse:
        """Handle async completion for OpenCode Zen."""
        try:
            # Get client
            openai_client = self._get_client(api_base, api_key)

            # Build request kwargs
            request_kwargs = {"model": model, "messages": messages, **optional_params}

            if timeout:
                request_kwargs["timeout"] = timeout

            # For empty API key, we need to make the request without Authorization header
            if api_key == "" or api_key is None:
                # Use the underlying HTTP client directly
                import json as json_lib

                http_client = openai_client._client

                # Build request body
                body = {
                    "model": model,
                    "messages": messages,
                }
                body.update(optional_params)

                # Make request without auth header
                response = await http_client.post(
                    f"{api_base}/chat/completions",
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()

                # Parse response
                data = response.json()

                # Build ModelResponse
                from litellm.types.utils import Choices, Message

                choice_data = data["choices"][0]
                message_data = choice_data["message"]

                message = Message(
                    content=message_data.get("content", ""),
                    role=message_data.get("role", "assistant"),
                )

                choice = Choices(
                    message=message,
                    finish_reason=choice_data.get("finish_reason", "stop"),
                    index=choice_data.get("index", 0),
                )

                model_response.choices = [choice]

                # Set usage if available
                if "usage" in data:
                    model_response.usage = data["usage"]

                return model_response
            else:
                # Use normal OpenAI client flow
                response = await openai_client.chat.completions.create(**request_kwargs)

                # Convert OpenAI response to LiteLLM ModelResponse
                from litellm.types.utils import Choices, Message

                openai_choice = response.choices[0]
                openai_message = openai_choice.message

                message = Message(
                    content=openai_message.content or "",
                    role=openai_message.role,
                )

                choice = Choices(
                    message=message,
                    finish_reason=openai_choice.finish_reason or "stop",
                    index=openai_choice.index,
                )

                model_response.choices = [choice]

                if hasattr(response, "usage") and response.usage:
                    model_response.usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }

                return model_response

        except Exception as e:
            logger.error(f"OpenCode Zen error: {e}")
            raise CustomLLMError(status_code=500, message=str(e))


# Create singleton instance
opencode_provider = OpenCodeProvider()


def register_opencode_provider():
    """Register the OpenCode Zen provider with LiteLLM."""
    import litellm

    # Add opencode to custom provider map
    if not hasattr(litellm, "custom_provider_map"):
        litellm.custom_provider_map = {}

    # Register our provider
    litellm.custom_provider_map["opencode"] = opencode_provider

    logger.info("Registered OpenCode Zen provider with LiteLLM")


# Auto-register on import
register_opencode_provider()
