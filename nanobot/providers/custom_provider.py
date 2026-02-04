"""Custom LiteLLM provider with configurable headers and token limits."""

import json
from dataclasses import dataclass
from typing import Any, Callable

from litellm import acompletion
from loguru import logger

from nanobot.providers.base import LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider


@dataclass
class CustomLLMConfig:
    """Custom provider configuration."""

    api_url: str | None = None
    api_key: str | None = None
    headers: dict[str, str] | None = None
    total_tokens_limit: int | None = None
    enforce_total_tokens_precheck: bool = False
    enforce_total_tokens_postcheck: bool = True
    api_validator: Callable[[dict[str, Any]], bool | None] | None = None
    default_model: str = "anthropic/claude-opus-4-5"
    api_key_env: str | list[str] | None = None

    def __post_init__(self) -> None:
        """Validate config values early."""
        if self.total_tokens_limit is not None and self.total_tokens_limit < 0:
            raise ValueError("total_tokens_limit must be >= 0")
        if self.headers is not None:
            for key, value in self.headers.items():
                if not key or not isinstance(key, str):
                    raise ValueError("headers keys must be non-empty strings")
                if not isinstance(value, str):
                    raise ValueError("headers values must be strings")


class CustomLLMProvider(LiteLLMProvider):
    """LiteLLM provider wrapper with custom headers and validation."""

    def __init__(
        self,
        config: CustomLLMConfig,
    ):
        super().__init__(
            api_key=config.api_key,
            api_base=config.api_url,
            default_model=config.default_model,
            api_key_env=config.api_key_env,
        )
        self.config = config
        self.total_tokens_used = 0
        self.is_token_limit_blocked = False

    def _build_validation_context(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Build validation context for api_validator."""
        return {
            "model": model,
            "messages": messages,
            "tools": tools,
            "api_base": self.api_base,
            "api_key": self.api_key,
            "headers": self.config.headers,
        }

    def _calculate_response_size(self, response: LLMResponse) -> int:
        """Calculate response size in UTF-8 bytes."""
        size = 0
        if response.content:
            size += len(response.content.encode("utf-8"))
        if response.tool_calls:
            payload = [
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
                for tool_call in response.tool_calls
            ]
            size += len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return size

    def _build_error_response(
        self,
        message: str,
        usage: dict[str, int] | None = None,
    ) -> LLMResponse:
        """Build error response with size metadata."""
        response = LLMResponse(
            content=message,
            finish_reason="error",
            usage=usage or {},
        )
        response.response_size_bytes = self._calculate_response_size(response)
        return response

    def _normalize_model(self, model: str) -> str:
        """Normalize model name with provider-specific prefixes."""
        if self.is_openrouter and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"

        if ("glm" in model.lower() or "zhipu" in model.lower()) and not (
            model.startswith("zhipu/")
            or model.startswith("zai/")
            or model.startswith("openrouter/")
        ):
            model = f"zai/{model}"

        if self.is_vllm:
            model = f"hosted_vllm/{model}"

        if "gemini" in model.lower() and not model.startswith("gemini/"):
            model = f"gemini/{model}"

        return model

    def _enforce_total_tokens_limit(self, response: LLMResponse) -> LLMResponse:
        """Return error response when total_tokens exceeds limit."""
        if not self.config.total_tokens_limit:
            return response
        total_tokens = response.usage.get("total_tokens") if response.usage else None
        if total_tokens is None:
            return response
        self.total_tokens_used += total_tokens
        if (
            self.total_tokens_used <= self.config.total_tokens_limit
            or not self.config.enforce_total_tokens_postcheck
        ):
            return response
        logger.warning(
            "total_tokens_used %s exceeds limit %s",
            self.total_tokens_used,
            self.config.total_tokens_limit,
        )
        self.is_token_limit_blocked = True
        message = (
            f"Error: total_tokens_used {self.total_tokens_used} exceeds limit "
            f"{self.config.total_tokens_limit}"
        )
        return self._build_error_response(message, usage=response.usage)

    def _should_block_precheck(self, max_tokens: int) -> bool:
        """Check if precheck should block the request."""
        if not self.config.total_tokens_limit:
            return False
        if not self.config.enforce_total_tokens_precheck:
            return False
        if self.is_token_limit_blocked:
            return True
        projected = self.total_tokens_used + max_tokens
        return projected > self.config.total_tokens_limit

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request via LiteLLM with custom headers."""
        if self._should_block_precheck(max_tokens):
            message = (
                f"Error: total_tokens_used {self.total_tokens_used} exceeds limit "
                f"{self.config.total_tokens_limit}"
            )
            return self._build_error_response(
                message,
                usage={"total_tokens": self.total_tokens_used},
            )

        model = self._normalize_model(model or self.config.default_model)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if self.api_base:
            kwargs["api_base"] = self.api_base

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if self.config.headers:
            kwargs["headers"] = dict(self.config.headers)

        if self.config.api_validator:
            try:
                is_valid = self.config.api_validator(
                    self._build_validation_context(model, messages, tools),
                )
            except Exception as e:
                logger.error(f"API validation error: {e}")
                return self._build_error_response(f"API validation error: {e}")
            if is_valid is False:
                return self._build_error_response("API validation failed")

        try:
            response = await acompletion(**kwargs)
            parsed = super()._parse_response(response)
            parsed.response_size_bytes = self._calculate_response_size(parsed)
            parsed = self._enforce_total_tokens_limit(parsed)
            return parsed
        except Exception as e:
            logger.error(f"LiteLLM request error: {e}")
            return self._build_error_response(f"Error calling LLM: {str(e)}")
