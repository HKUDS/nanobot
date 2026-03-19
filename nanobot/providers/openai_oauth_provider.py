"""OpenAI Responses provider authenticated via official OAuth flow."""

from __future__ import annotations

import asyncio
from typing import Any

from oauth_cli_kit import OAuthProviderConfig, get_token
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.custom_provider import CustomProvider
from nanobot.providers.openai_codex_provider import (
    _convert_messages,
    _convert_tools,
    _prompt_cache_key,
)

DEFAULT_OPENAI_API_BASE = "https://api.openai.com/v1"

OPENAI_OAUTH_PROVIDER = OAuthProviderConfig(
    client_id="app_EMoamEEZ73f0CkXaXp7hrann",
    authorize_url="https://auth.openai.com/oauth/authorize",
    token_url="https://auth.openai.com/oauth/token",
    redirect_uri="http://localhost:1455/auth/callback",
    scope="openid profile email offline_access",
    jwt_claim_path="https://api.openai.com/auth",
    account_id_claim="chatgpt_account_id",
    default_originator="nanobot",
    token_filename="openai.json",
)


class OpenAIOAuthProvider(LLMProvider):
    """Call OpenAI's Responses API using an OAuth access token."""

    def __init__(
        self,
        default_model: str = "openai-oauth/gpt-5.1",
        api_base: str | None = None,
    ):
        super().__init__(api_key=None, api_base=api_base or DEFAULT_OPENAI_API_BASE)
        self.default_model = default_model
        self._client = AsyncOpenAI(api_key="oauth-placeholder", base_url=self.api_base)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        effective_model = _strip_model_prefix(model or self.default_model)
        system_prompt, input_items = _convert_messages(messages)

        try:
            token = await asyncio.to_thread(get_token, provider=OPENAI_OAUTH_PROVIDER)
            client = self._client.with_options(api_key=token.access)

            request: dict[str, Any] = {
                "model": effective_model,
                "input": input_items,
                "max_output_tokens": max(1, max_tokens),
                "temperature": temperature,
                "store": False,
                "text": {"verbosity": "medium"},
                "prompt_cache_key": _prompt_cache_key(messages),
            }
            if system_prompt:
                request["instructions"] = system_prompt
            if reasoning_effort:
                request["reasoning"] = {"effort": reasoning_effort}
            if tools:
                request["tools"] = _convert_tools(tools)
                request["tool_choice"] = tool_choice or "auto"
                request["parallel_tool_calls"] = True

            extra_headers: dict[str, str] | None = None
            if token.account_id:
                extra_headers = {"chatgpt-account-id": token.account_id}

            response = await client.responses.create(
                **request,
                extra_headers=extra_headers,
            )
            return CustomProvider._parse_responses_api(response.model_dump(mode="json"))
        except Exception as e:
            return LLMResponse(
                content=f"Error calling OpenAI OAuth: {e}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-oauth/") or model.startswith("openai_oauth/"):
        return model.split("/", 1)[1]
    return model
