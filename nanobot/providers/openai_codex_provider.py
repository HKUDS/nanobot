"""OpenAI Codex Responses Provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from loguru import logger
from oauth_cli_kit import get_token as get_codex_token

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.openai_responses import (
    consume_sse,
    convert_messages,
    convert_tools,
)

DEFAULT_CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_ORIGINATOR = "nanobot"


class OpenAICodexProvider(LLMProvider):
    """Use Codex OAuth to call the Responses API."""

    supports_progress_deltas = True

    def __init__(self, default_model: str = "openai-codex/gpt-5.1-codex"):
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model

    async def _call_codex(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Shared request logic for both chat() and chat_stream()."""
        model = model or self.default_model
        system_prompt, input_items = convert_messages(messages)

        token = await asyncio.to_thread(get_codex_token)
        headers = _build_headers(token.account_id, token.access)

        body: dict[str, Any] = {
            "model": _strip_model_prefix(model),
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(messages),
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }
        if reasoning_effort and reasoning_effort.lower() != "none":
            body["reasoning"] = {"effort": reasoning_effort}
        if tools:
            body["tools"] = convert_tools(tools)

        try:
            try:
                content, tool_calls, finish_reason = await _request_codex(
                    DEFAULT_CODEX_URL, headers, body, verify=True,
                    on_content_delta=on_content_delta,
                )
            except Exception as e:
                if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                    raise
                logger.warning("SSL verification failed for Codex API; retrying with verify=False")
                content, tool_calls, finish_reason = await _request_codex(
                    DEFAULT_CODEX_URL, headers, body, verify=False,
                    on_content_delta=on_content_delta,
                )
            return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish_reason)
        except Exception as e:
            msg = f"Error calling Codex: {e}"
            retry_after = getattr(e, "retry_after", None) or self._extract_retry_after(msg)
            return LLMResponse(content=msg, finish_reason="error", retry_after=retry_after)

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
        model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return await self._call_codex(messages, tools, model, reasoning_effort, tool_choice)

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
        model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        return await self._call_codex(messages, tools, model, reasoning_effort, tool_choice, on_content_delta)

    def get_default_model(self) -> str:
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _build_headers(account_id: str, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": DEFAULT_ORIGINATOR,
        "User-Agent": "nanobot (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


class _CodexHTTPError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


async def _request_codex(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    verify: bool,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str]:
    async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                text = await response.aread()
                retry_after = LLMProvider._extract_retry_after_from_headers(response.headers)
                raise _CodexHTTPError(
                    _friendly_error(response.status_code, text.decode("utf-8", "ignore")),
                    retry_after=retry_after,
                )
            return await consume_sse(response, on_content_delta)


def _prompt_cache_key(messages: list[dict[str, Any]]) -> str:
    raw = json.dumps(messages, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _friendly_error(status_code: int, raw: str) -> str:
    if status_code == 429:
        return "ChatGPT usage quota exceeded or rate limit triggered. Please try again later."
    return f"HTTP {status_code}: {raw}"
