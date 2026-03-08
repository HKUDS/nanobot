"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any

import json_repair
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from nanobot.config.schema import LLMRetryConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ProviderRequestError, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str = "http://localhost:8000/v1",
        default_model: str = "default",
        retry_config: LLMRetryConfig | None = None,
    ):
        super().__init__(api_key, api_base, retry_config=retry_config)
        self.default_model = default_model
        # Keep affinity stable for this provider instance to improve backend cache locality.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    async def _chat_once(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                         model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                         reasoning_effort: str | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except APIStatusError as e:
            raise ProviderRequestError(
                message=f"Error calling Custom provider: {str(e)}",
                retryable=e.status_code in set(self.retry_config.retryable_status_codes),
                status_code=e.status_code,
            ) from e
        except (APITimeoutError, APIConnectionError) as e:
            raise self._wrap_exception(e, prefix="Error calling Custom provider") from e
        except Exception as e:
            raise self._wrap_exception(e, prefix="Error calling Custom provider") from e

    def _parse(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(id=tc.id, name=tc.function.name,
                            arguments=json_repair.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments)
            for tc in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content, tool_calls=tool_calls, finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def get_default_model(self) -> str:
        return self.default_model

