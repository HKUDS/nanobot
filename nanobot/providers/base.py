"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import time


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None  # Kimi, DeepSeek-R1 etc.

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Implementations should handle the specifics of each provider's API
    while maintaining a consistent interface.
    """

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base
        self._provider_name: str = "unknown"  # Subclasses should set this

    def _get_provider_name(self) -> str:
        """Get the name of this provider (override in subclasses)."""
        return self._provider_name

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request with audit logging.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions.
            model: Model identifier (provider-specific).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        # Import here to avoid circular dependency
        from nanobot.providers.audit_logger import (
            APILogEntry,
            get_logger,
        )

        start_time = time.time()
        provider_name = self._get_provider_name()
        used_model = model or self.get_default_model()

        # Create log entry for request
        entry = APILogEntry.from_request(
            model=used_model,
            provider=provider_name,
            messages=messages,
            tools=tools,
        )

        try:
            # Call the actual implementation
            response = await self._chat_implementation(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Add response data to entry
            tool_names = [tc.name for tc in response.tool_calls] if response.tool_calls else None
            entry.with_response(
                content=response.content,
                tool_calls=tool_names,
                usage=response.usage,
                finish_reason=response.finish_reason,
                duration_ms=duration_ms,
            )

            return response

        except Exception as e:
            # Log error
            duration_ms = (time.time() - start_time) * 1000
            entry.with_error(str(e))
            entry.duration_ms = duration_ms

            # Re-raise the original exception
            raise

        finally:
            # Log the entry
            get_logger().log(entry)

    @abstractmethod
    async def _chat_implementation(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """
        Internal implementation of chat (override this in subclasses).

        This is where the actual API call happens. The base `chat()` method
        handles audit logging around this call.
        """
        pass

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace empty text content that causes provider 400 errors.

        Empty content can appear when MCP tools return nothing. Most providers
        reject empty-string content or empty text blocks in list content.
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = None if (msg.get("role") == "assistant" and msg.get("tool_calls")) else "(empty)"
                result.append(clean)
                continue

            if isinstance(content, list):
                filtered = [
                    item for item in content
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    )
                ]
                if len(filtered) != len(content):
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            result.append(msg)
        return result

    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass
