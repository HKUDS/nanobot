"""LiteLLM provider implementation for multi-provider support."""

import os
from typing import Any

import litellm
from litellm import acompletion
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5"
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model

        # Detect OpenRouter by api_key prefix or explicit api_base
        self.is_openrouter = (
            (api_key and api_key.startswith("sk-or-")) or
            (api_base and "openrouter" in api_base)
        )

        # Track if using custom endpoint (vLLM, etc.)
        self.is_vllm = bool(api_base) and not self.is_openrouter

        # Configure LiteLLM based on provider
        if api_key:
            if self.is_openrouter:
                # OpenRouter mode - set key
                os.environ["OPENROUTER_API_KEY"] = api_key
            elif self.is_vllm:
                # vLLM/custom endpoint - uses OpenAI-compatible API
                os.environ["HOSTED_VLLM_API_KEY"] = api_key
            elif "deepseek" in default_model:
                os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
            elif "anthropic" in default_model:
                os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            elif "openai" in default_model or "gpt" in default_model:
                os.environ.setdefault("OPENAI_API_KEY", api_key)
            elif "gemini" in default_model.lower():
                os.environ.setdefault("GEMINI_API_KEY", api_key)
            elif "zhipu" in default_model or "glm" in default_model or "zai" in default_model:
                os.environ.setdefault("ZHIPUAI_API_KEY", api_key)
            elif "groq" in default_model:
                os.environ.setdefault("GROQ_API_KEY", api_key)
            elif "moonshot" in default_model or "kimi" in default_model:
                os.environ.setdefault("MOONSHOT_API_KEY", api_key)
                os.environ.setdefault("MOONSHOT_API_BASE", api_base or "https://api.moonshot.cn/v1")

        if api_base:
            litellm.api_base = api_base

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model

        # For OpenRouter, prefix model name if not already prefixed
        if self.is_openrouter and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"

        # For Zhipu/Z.ai, ensure prefix is present
        # Handle cases like "glm-4.7-flash" -> "zai/glm-4.7-flash"
        if ("glm" in model.lower() or "zhipu" in model.lower()) and not (
            model.startswith("zhipu/") or
            model.startswith("zai/") or
            model.startswith("openrouter/")
        ):
            model = f"zai/{model}"

        # For Moonshot/Kimi, ensure moonshot/ prefix (before vLLM check)
        if ("moonshot" in model.lower() or "kimi" in model.lower()) and not (
            model.startswith("moonshot/") or model.startswith("openrouter/")
        ):
            model = f"moonshot/{model}"

        # For Gemini, ensure gemini/ prefix if not already present
        if "gemini" in model.lower() and not model.startswith("gemini/"):
            model = f"gemini/{model}"

        # For vLLM, use hosted_vllm/ prefix per LiteLLM docs
        # Convert openai/ prefix to hosted_vllm/ if user specified it
        if self.is_vllm:
            model = f"hosted_vllm/{model}"

        # kimi-k2.5 only supports temperature=1.0
        if "kimi-k2.5" in model.lower():
            temperature = 1.0

        # Format content for multimodal support (vision)
        formatted_messages = self._format_messages_for_provider(messages, model)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Pass api_base directly for custom endpoints (vLLM, etc.)
        if self.api_base:
            kwargs["api_base"] = self.api_base

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    def _format_messages_for_provider(
        self, messages: list[dict[str, Any]], model: str
    ) -> list[dict[str, Any]]:
        """
        Format all messages in the list for the specific provider.

        Args:
            messages: List of message dicts.
            model: Model name.

        Returns:
            Formatted messages list.
        """
        formatted = []
        for msg in messages:
            formatted_msg = {"role": msg["role"]}
            if "content" in msg:
                formatted_msg["content"] = self._format_content_for_provider(
                    msg["content"], model
                )
            if "tool_calls" in msg:
                formatted_msg["tool_calls"] = msg["tool_calls"]
            if msg.get("role") == "tool":
                formatted_msg["tool_call_id"] = msg.get("tool_call_id")
                formatted_msg["name"] = msg.get("name")
            formatted.append(formatted_msg)
        return formatted

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model

    def _has_image_content(self, content: Any) -> bool:
        """Check if content contains image data."""
        if isinstance(content, str):
            return False
        if isinstance(content, list):
            return any(item.get("type") == "image_url" for item in content)
        return False

    def _format_content_for_provider(self, content: Any, model: str) -> Any:
        """
        Format message content for specific provider's multimodal format.

        Args:
            content: Message content (str or list with images)
            model: Model name to determine format

        Returns:
            Formatted content for the provider
        """
        # Handle text-only content
        if isinstance(content, str):
            return content

        # No images, return as-is
        if not self._has_image_content(content):
            return content

        # Format for specific provider
        model_lower = model.lower()
        if "claude" in model_lower or "anthropic" in model_lower:
            return self._format_for_claude(content)
        elif "gemini" in model_lower:
            return self._format_for_gemini(content)
        else:
            # Default to OpenAI format (already in image_url format)
            return content

    def _format_for_claude(self, content: list) -> list:
        """
        Format content for Claude vision API.

        Claude expects: {"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}
        """
        formatted = []
        for item in content:
            if item.get("type") == "image_url":
                # Parse data URL (format: data:mime/type;base64,data)
                url = item["image_url"]["url"]
                if url.startswith("data:"):
                    try:
                        # Remove "data:" prefix and split
                        mime_and_data = url[5:]
                        if ";base64," in mime_and_data:
                            mime_type, b64_data = mime_and_data.split(";base64,", 1)
                            formatted.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": b64_data
                                }
                            })
                        else:
                            logger.warning(f"Invalid data URL format for Claude: {url[:50]}...")
                            continue
                    except Exception as e:
                        logger.error(f"Error formatting image for Claude: {e}")
                        continue
                else:
                    # Regular URL (not supported for Claude, need base64)
                    logger.warning("Claude vision requires base64-encoded images, not URLs")
                    continue
            elif item.get("type") == "text":
                formatted.append({"type": "text", "text": item["text"]})
        return formatted

    def _format_for_gemini(self, content: list) -> list:
        """
        Format content for Gemini vision API.

        Gemini expects: {"inline_data": {"mime_type": "...", "data": "..."}}
        """
        parts = []
        for item in content:
            if item.get("type") == "image_url":
                # Parse data URL
                url = item["image_url"]["url"]
                if url.startswith("data:"):
                    try:
                        mime_and_data = url[5:]
                        if ";base64," in mime_and_data:
                            mime_type, b64_data = mime_and_data.split(";base64,", 1)
                            parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": b64_data
                                }
                            })
                        else:
                            logger.warning(f"Invalid data URL format for Gemini: {url[:50]}...")
                            continue
                    except Exception as e:
                        logger.error(f"Error formatting image for Gemini: {e}")
                        continue
                else:
                    logger.warning("Gemini vision requires base64-encoded images, not URLs")
                    continue
            elif item.get("type") == "text":
                parts.append({"text": item["text"]})
        return parts
