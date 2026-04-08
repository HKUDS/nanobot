"""Custom provider using OpenAI SDK Responses API."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.openai_responses import (
    consume_sdk_stream,
    convert_messages,
    convert_tools,
    parse_response_output,
)


class CustomResponsesProvider(LLMProvider):
    """Direct OpenAI-compatible Responses provider.

    Uses ``AsyncOpenAI`` with ``base_url=api_base`` and calls
    ``client.responses.create(...)`` for both non-streaming and streaming paths.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gpt-4.1",
        extra_headers: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}

        default_headers = {"x-session-affinity": uuid.uuid4().hex}
        if extra_headers:
            default_headers.update(extra_headers)

        self._client = AsyncOpenAI(
            api_key=api_key or "no-key",
            base_url=api_base,
            default_headers=default_headers,
            max_retries=0,
        )

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        parallel_tool_calls: bool | None,
    ) -> dict[str, Any]:
        model_name = model or self.default_model
        sanitized_messages = self._sanitize_empty_content(messages)
        instructions, input_items = convert_messages(sanitized_messages)
        instructions = self._with_developer_instructions(sanitized_messages, instructions)

        body: dict[str, Any] = {
            "model": model_name,
            "instructions": instructions or None,
            "input": input_items,
            "max_output_tokens": max(1, max_tokens),
        }

        if tools:
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = tool_choice or "auto"

        if parallel_tool_calls is not None:
            body["parallel_tool_calls"] = parallel_tool_calls

        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}

        return body

    @staticmethod
    def _with_developer_instructions(
        messages: list[dict[str, Any]],
        base_instructions: str,
    ) -> str:
        developer_parts: list[str] = []
        for message in messages:
            if message.get("role") != "developer":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                developer_parts.append(content)

        developer_text = "\n\n".join(developer_parts).strip()
        if not developer_text:
            return base_instructions
        if not base_instructions:
            return developer_text
        return f"{base_instructions}\n\n{developer_text}"

    @staticmethod
    def _handle_error(e: Exception) -> LLMResponse:
        response = getattr(e, "response", None)
        body = getattr(e, "body", None) or getattr(response, "text", None)
        body_text = str(body).strip() if body is not None else ""
        msg = f"Error: {body_text[:500]}" if body_text else f"Error calling LLM: {e}"
        retry_after = LLMProvider._extract_retry_after_from_headers(
            getattr(response, "headers", None)
        )
        if retry_after is None:
            retry_after = LLMProvider._extract_retry_after(msg)
        return LLMResponse(content=msg, finish_reason="error", retry_after=retry_after)

    @staticmethod
    def _normalize_stream_result(response: LLMResponse) -> LLMResponse:
        """Apply deterministic finish-reason policy for stream-first assembly.

        Rules:
        - Tool-bearing turns are never treated as empty-final failures.
        - ``length`` with no text and no tool calls is escalated to ``error``.
        - ``stop`` with no text and no tool calls is:
          - ``empty`` when completion metadata exists (genuine empty success),
          - ``error`` when completion metadata is missing (parser/stream loss).
        """
        content = response.content.strip() if isinstance(response.content, str) else ""
        has_text = bool(content)
        has_tool_calls = bool(response.tool_calls)
        has_completion_metadata = bool(response.usage)

        if has_tool_calls:
            return LLMResponse(
                content=content or None,
                tool_calls=response.tool_calls,
                finish_reason=response.finish_reason,
                usage=response.usage,
                retry_after=response.retry_after,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
                error_status_code=response.error_status_code,
                error_kind=response.error_kind,
                error_type=response.error_type,
                error_code=response.error_code,
                error_retry_after_s=response.error_retry_after_s,
                error_should_retry=response.error_should_retry,
            )

        if response.finish_reason == "length" and not has_text:
            return LLMResponse(
                content="Error: incomplete stream with no content or tool calls",
                finish_reason="error",
                usage=response.usage,
                reasoning_content=response.reasoning_content,
            )

        if response.finish_reason == "stop" and not has_text:
            if has_completion_metadata:
                return LLMResponse(
                    content=None,
                    finish_reason="empty",
                    usage=response.usage,
                    reasoning_content=response.reasoning_content,
                )
            return LLMResponse(
                content="Error: stream ended without completion metadata",
                finish_reason="error",
                usage=response.usage,
                reasoning_content=response.reasoning_content,
            )

        return LLMResponse(
            content=content or None,
            tool_calls=response.tool_calls,
            finish_reason=response.finish_reason,
            usage=response.usage,
            retry_after=response.retry_after,
            reasoning_content=response.reasoning_content,
            thinking_blocks=response.thinking_blocks,
            error_status_code=response.error_status_code,
            error_kind=response.error_kind,
            error_type=response.error_type,
            error_code=response.error_code,
            error_retry_after_s=response.error_retry_after_s,
            error_should_retry=response.error_should_retry,
        )

    async def _chat_via_stream(
        self,
        body: dict[str, Any],
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        request_body = dict(body)
        request_body["stream"] = True
        stream_or_response = await self._client.responses.create(**request_body)

        # Compatibility fallback for mocked/non-stream SDK objects.
        if callable(getattr(stream_or_response, "model_dump", None)) or isinstance(
            stream_or_response,
            dict,
        ):
            return self._normalize_stream_result(parse_response_output(stream_or_response))

        content, tool_calls, finish_reason, usage, reasoning_content = await consume_sdk_stream(
            stream_or_response,
            on_content_delta,
        )
        return self._normalize_stream_result(
            LLMResponse(
                content=content or None,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                reasoning_content=reasoning_content,
            )
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> LLMResponse:
        body = self._build_body(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
        )
        try:
            return await self._chat_via_stream(body)
        except Exception as e:
            return self._handle_error(e)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> LLMResponse:
        body = self._build_body(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
        )
        try:
            return await self._chat_via_stream(body, on_content_delta=on_content_delta)
        except Exception as e:
            return self._handle_error(e)

    def get_default_model(self) -> str:
        return self.default_model
