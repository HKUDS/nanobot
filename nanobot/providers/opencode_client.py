"""OpenCode Zen provider that subclasses OpenAI SDK to support empty API keys."""

from typing import Any, Optional, Union, AsyncIterator
import httpx
from openai import AsyncOpenAI
from openai._base_client import AsyncAPIClient
from openai._models import FinalRequestOptions
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from loguru import logger


class OpenCodeAsyncOpenAI(AsyncOpenAI):
    """Extended AsyncOpenAI that supports empty API keys for OpenCode Zen.

    OpenCode Zen requires api_key="" (empty string) for free models, but
    the standard OpenAI SDK doesn't handle this well. This subclass fixes that.
    """

    def __init__(self, *args, **kwargs):
        # Allow empty api_key by setting a placeholder then removing it
        api_key = kwargs.get("api_key", "")
        if api_key == "":
            # Set placeholder temporarily
            kwargs["api_key"] = "opencode-placeholder"
            self._opencode_empty_key = True
        else:
            self._opencode_empty_key = False

        super().__init__(*args, **kwargs)

        # Restore empty key
        if self._opencode_empty_key:
            self.api_key = ""

    async def _request(self, method: str, url: Union[str, httpx.URL], **kwargs) -> Any:
        """Override _request to skip Authorization header when api_key is empty."""
        if self._opencode_empty_key:
            # Remove Authorization header for this request
            headers = kwargs.get("headers", {})
            if "Authorization" in headers:
                del headers["Authorization"]
            kwargs["headers"] = headers

        return await super()._request(method, url, **kwargs)

    async def _post(self, url: str, **kwargs) -> Any:
        """Override _post to skip Authorization header when api_key is empty."""
        if self._opencode_empty_key:
            headers = kwargs.get("headers", {})
            if "Authorization" in headers:
                del headers["Authorization"]
            kwargs["headers"] = headers

        return await super()._post(url, **kwargs)


class OpenCodeZenProvider:
    """LiteLLM-compatible provider for OpenCode Zen using custom OpenAI client."""

    def __init__(self):
        self._clients: dict[str, OpenCodeAsyncOpenAI] = {}

    def get_client(self, api_base: str) -> OpenCodeAsyncOpenAI:
        """Get or create OpenCode client."""
        if api_base not in self._clients:
            self._clients[api_base] = OpenCodeAsyncOpenAI(
                api_key="",  # Empty key for OpenCode Zen
                base_url=api_base,
            )
        return self._clients[api_base]

    async def acompletion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        api_base: str = "https://opencode.ai/zen/v1",
        api_key: str = "",
        **kwargs,
    ) -> ChatCompletion:
        """Make completion request to OpenCode Zen."""
        client = self.get_client(api_base)

        response = await client.chat.completions.create(model=model, messages=messages, **kwargs)

        return response


# Global instance
opencode_provider = OpenCodeZenProvider()
