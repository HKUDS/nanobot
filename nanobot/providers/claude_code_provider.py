"""Claude Code subscription provider.

Uses the OAuth token from ~/.claude/.credentials.json to call the Anthropic
API through LiteLLM. LiteLLM automatically recognises the ``sk-ant-oat``
prefix and sends the correct ``Authorization: Bearer`` header and
``anthropic-beta: oauth-2025-04-20`` header — no extra configuration needed.

Token refresh is NOT done here — Claude Code manages its own token lifecycle.
"""

from __future__ import annotations

import json
from typing import Any

from nanobot.providers.base import LLMResponse
from nanobot.providers.claude_code_credentials import get_access_token
from nanobot.providers.litellm_provider import LiteLLMProvider


class ClaudeCodeProvider(LiteLLMProvider):
    """LiteLLM-based provider that authenticates via Claude Code OAuth tokens."""

    def __init__(self, default_model: str = "claude-sonnet-4-6"):
        try:
            token = get_access_token()
        except (FileNotFoundError, ValueError, RuntimeError):
            token = ""
        super().__init__(api_key=token, default_model=default_model)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        # Re-read token each call — Claude Code may have refreshed it
        try:
            self.api_key = get_access_token()
        except (RuntimeError, FileNotFoundError, ValueError, json.JSONDecodeError) as e:
            return LLMResponse(content=str(e), finish_reason="error")
        return await super().chat(messages, tools, model, max_tokens, temperature)
