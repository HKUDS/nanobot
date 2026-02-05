"""Native Google Gemini provider implementation using google-genai SDK."""

import asyncio
import logging
from typing import Any

from google import genai
from google.genai import types

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

logger = logging.getLogger(__name__)

# Default timeout for API requests (seconds)
DEFAULT_TIMEOUT = 120


class GeminiProvider(LLMProvider):
    """
    Native Google Gemini provider using google-genai SDK.

    Supports:
    - Gemini Pro, Gemini Flash, etc.
    - System instructions
    - Multi-turn conversations

    Note: Tool calling not yet implemented - will raise NotImplementedError if tools provided.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gemini-2.5-flash",
        timeout: int = DEFAULT_TIMEOUT,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.timeout = timeout

        # Initialize client - api_key is required for Gemini Developer API
        # If api_key is None, SDK will try to use GOOGLE_GENAI_API_KEY env var
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = genai.Client()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send a chat completion request via Gemini API.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions. Not yet implemented.
            model: Model identifier (e.g., 'gemini-2.5-flash').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature (0-1).
            system: System instruction.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with content.

        Raises:
            NotImplementedError: If tools parameter is provided.
            genai.APIError: For Gemini API specific errors.
        """
        model_name = model or self.default_model

        # Tools not yet implemented
        if tools:
            raise NotImplementedError(
                "Tool calling is not yet supported for Gemini provider. "
                "Use OpenAI or Anthropic provider for tool calling."
            )

        # Convert messages to google-genai format
        contents = self._convert_messages_to_gemini(messages)

        # Build generation config
        gen_config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system if system else None,
        )

        try:
            # Run synchronous SDK call in thread pool to avoid blocking event loop
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.models.generate_content,
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                ),
                timeout=self.timeout,
            )
            return self._parse_response(response)
        except asyncio.TimeoutError:
            logger.error(f"Gemini API timeout after {self.timeout}s")
            return LLMResponse(
                content=f"Gemini API timeout after {self.timeout}s",
                finish_reason="error",
            )
        except genai.APIError as e:
            logger.error(f"Gemini API error: {e}", exc_info=True)
            return LLMResponse(
                content=f"Gemini API error: {e.message}",
                finish_reason="error",
            )
        except Exception as e:
            logger.exception("Unexpected Gemini API error")
            return LLMResponse(
                content=f"Error calling Gemini API: {str(e)}",
                finish_reason="error",
            )

    def _convert_messages_to_gemini(self, messages: list[dict[str, Any]]) -> list[types.Content]:
        """
        Convert OpenAI-style messages to google-genai format.

        Handles multi-turn conversations by preserving both user and assistant messages.

        Args:
            messages: List of message dicts with 'role' and 'content'.

        Returns:
            List of google-genai Content objects.
        """
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=content)]
                ))
            elif role == "assistant":
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part(text=content)]
                ))
            # Skip system messages - they're handled via system_instruction
            elif role == "system":
                continue

        return contents

    def _parse_response(self, response: Any) -> LLMResponse:
        """
        Parse google-genai response into our standard format.

        Args:
            response: Raw response from google-genai API.

        Returns:
            LLMResponse with parsed content and metadata.
        """
        text_content = None

        # Try to get text from response.text property first
        if hasattr(response, "text") and response.text:
            text_content = response.text
        # Fallback: extract from candidates if response.text is None
        elif hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "content") and candidate.content:
                if hasattr(candidate.content, "parts") and candidate.content.parts:
                    parts_text = []
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            parts_text.append(part.text)
                    if parts_text:
                        text_content = "".join(parts_text)

        # Parse usage
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }

        # Parse finish reason
        finish_reason = "stop"
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "finish_reason"):
                finish_reason = str(candidate.finish_reason.value) if candidate.finish_reason else "stop"

        # Tool calls (not implemented yet for this version)
        tool_calls = []

        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
