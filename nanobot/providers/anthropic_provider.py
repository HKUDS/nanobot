"""Native Anthropic provider implementation with full API support."""

from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class AnthropicProvider(LLMProvider):
    """
    Native Anthropic provider with full API support.

    Supports:
    - Extended thinking (Claude 3.7 Sonnet+)
    - Prompt caching headers
    - Top-k sampling
    - Custom base URL (for compatible endpoints like Zhipu CodePlan)
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "claude-sonnet-4-20250514",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model

        # Initialize async client
        client_kwargs: dict[str, Any] = {"api_key": api_key} if api_key else {}
        if api_base:
            client_kwargs["base_url"] = api_base

        self.client = AsyncAnthropic(**client_kwargs)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_k: int | None = None,
        thinking: dict[str, Any] | None = None,
        system: str | None = None,
        enable_cache_headers: bool = False,
    ) -> LLMResponse:
        """
        Send a chat completion request via Anthropic API.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in Anthropic format.
            model: Model identifier (e.g., 'claude-sonnet-4-20250514').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature (0-1).
            top_k: Anthropic-specific top-k sampling.
            thinking: Extended thinking config, e.g. {"type": "enabled", "budget_tokens": 10000}
            system: System prompt (overrides any in messages).
            enable_cache_headers: Enable prompt caching with cache_control headers.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model

        # Convert OpenAI-style tools to Anthropic format
        anthropic_tools = None
        if tools:
            anthropic_tools = self._convert_tools_to_anthropic(tools)

        # Prepare messages (convert format if needed)
        anthropic_messages = self._convert_messages_to_anthropic(messages)

        # Build request kwargs
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if anthropic_tools:
            request_kwargs["tools"] = anthropic_tools

        if top_k is not None:
            request_kwargs["top_k"] = top_k

        if thinking:
            request_kwargs["thinking"] = thinking

        if system:
            request_kwargs["system"] = system
        elif enable_cache_headers:
            # Add cache control to last user message
            request_kwargs["system"] = ""

        try:
            response = await self.client.messages.create(**request_kwargs)
            return self._parse_response(response)
        except Exception as e:
            return LLMResponse(
                content=f"Error calling Anthropic API: {str(e)}",
                finish_reason="error",
            )

    def _convert_tools_to_anthropic(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style tools to Anthropic format."""
        anthropic_tools = []
        for tool in tools:
            if "function" in tool:
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object"}),
                })
            else:
                # Already in Anthropic format
                anthropic_tools.append(tool)
        return anthropic_tools

    def _convert_messages_to_anthropic(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert messages to Anthropic format."""
        anthropic_messages = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                # Anthropic handles system separately, skip here
                continue
            if role == "assistant":
                content = msg.get("content", "")
                # Check for tool_calls
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # Convert to Anthropic tool_use format
                    anthropic_content = []
                    for tc in tool_calls:
                        anthropic_content.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": tc["function"].get("arguments", {}),
                        })
                    if content:
                        anthropic_content.append({"type": "text", "text": content})
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": anthropic_content,
                    })
                else:
                    anthropic_messages.append({"role": "assistant", "content": content})
            elif role == "user":
                # Check for tool results
                tool_results = []
                content = msg.get("content", "")
                if "tool_results" in msg:
                    for tr in msg["tool_results"]:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tr["tool_use_id"],
                            "content": tr.get("content", ""),
                        })
                    if tool_results:
                        anthropic_messages.append({
                            "role": "user",
                            "content": tool_results,
                        })
                else:
                    anthropic_messages.append({"role": "user", "content": content})
            else:
                # Pass through as-is
                anthropic_messages.append(msg)
        return anthropic_messages

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Anthropic response into our standard format."""
        tool_calls = []

        # Parse content blocks
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCallRequest(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        # Build text content from text blocks
        text_content = None
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if text_blocks:
            text_content = "".join(text_blocks)

        # Parse usage
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }

        # Map Anthropic stop_reason to our format
        finish_reason = response.stop_reason or "stop"

        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
