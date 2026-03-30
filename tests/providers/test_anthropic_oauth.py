"""Unit tests for Anthropic OAuth token (Claude Code subscription) support.

Tests verify that when an OAuth token (sk-ant-oat...) is used:
1. Bearer auth is used (Authorization header), not x-api-key
2. Claude Code identity headers are injected (user-agent, x-app)
3. Required beta headers are present in the request payload
4. Claude Code system prompt is prepended
5. Tool names are normalized to CC canonical casing
"""

from __future__ import annotations

import pytest

from nanobot.providers.anthropic_provider import (
    _CLAUDE_CODE_SYSTEM_PROMPT,
    _CLAUDE_CODE_VERSION,
    _OAUTH_BETAS,
    _is_oauth_token,
    _merge_beta_header,
    _to_claude_code_name,
    AnthropicProvider,
)

_FAKE_OAUTH_TOKEN = "sk-ant-oat01-fake-test-token-" + "x" * 60
_FAKE_API_KEY = "sk-ant-api01-fake-test-key-" + "x" * 60


# ---------------------------------------------------------------------------
# Pure-function unit tests (no network)
# ---------------------------------------------------------------------------

class TestOAuthDetection:
    def test_detects_oauth_token(self):
        assert _is_oauth_token("sk-ant-oat01-abc") is True

    def test_rejects_api_key(self):
        assert _is_oauth_token("sk-ant-api01-abc") is False

    def test_rejects_none(self):
        assert _is_oauth_token(None) is False

    def test_rejects_empty(self):
        assert _is_oauth_token("") is False


class TestBetaHeaderMerge:
    def test_merges_into_empty(self):
        result = _merge_beta_header({}, ["beta-a", "beta-b"])
        assert result["anthropic-beta"] == "beta-a,beta-b"

    def test_deduplicates(self):
        result = _merge_beta_header({"anthropic-beta": "beta-a"}, ["beta-a", "beta-b"])
        betas = result["anthropic-beta"].split(",")
        assert betas.count("beta-a") == 1
        assert "beta-b" in betas

    def test_preserves_other_headers(self):
        result = _merge_beta_header({"x-other": "val"}, ["beta-a"])
        assert result["x-other"] == "val"


class TestToolNameNormalization:
    def test_known_tools_normalized(self):
        assert _to_claude_code_name("read") == "Read"
        assert _to_claude_code_name("BASH") == "Bash"
        assert _to_claude_code_name("webfetch") == "WebFetch"
        assert _to_claude_code_name("websearch") == "WebSearch"
        assert _to_claude_code_name("write") == "Write"
        assert _to_claude_code_name("edit") == "Edit"

    def test_unknown_tool_passthrough(self):
        assert _to_claude_code_name("my_custom_tool") == "my_custom_tool"


# ---------------------------------------------------------------------------
# Provider construction tests: verify auth method and identity headers
# ---------------------------------------------------------------------------

class TestProviderConstruction:
    def test_oauth_uses_bearer_auth(self):
        """SDK must use Authorization: Bearer for OAuth tokens, and must NOT send X-Api-Key."""
        provider = AnthropicProvider(api_key=_FAKE_OAUTH_TOKEN, default_model="claude-sonnet-4-6")
        auth_headers = provider._client.auth_headers
        assert "Authorization" in auth_headers
        assert auth_headers["Authorization"].startswith("Bearer ")
        assert _FAKE_OAUTH_TOKEN in auth_headers["Authorization"]
        # X-Api-Key must be absent — Anthropic validates it before Authorization and returns 401
        assert "X-Api-Key" not in auth_headers

    def test_oauth_injects_claude_code_identity_headers(self):
        """user-agent and x-app must identify the client as Claude Code."""
        provider = AnthropicProvider(api_key=_FAKE_OAUTH_TOKEN, default_model="claude-sonnet-4-6")
        assert f"claude-cli/{_CLAUDE_CODE_VERSION}" in provider.extra_headers.get("user-agent", "")
        assert provider.extra_headers.get("x-app") == "cli"

    def test_api_key_uses_x_api_key_auth(self):
        """Regular API keys must use X-Api-Key header, not Bearer."""
        provider = AnthropicProvider(api_key=_FAKE_API_KEY, default_model="claude-sonnet-4-6")
        auth_headers = provider._client.auth_headers
        assert "X-Api-Key" in auth_headers
        assert _FAKE_API_KEY in auth_headers["X-Api-Key"]
        # Bearer should NOT be set (or should be None/empty)
        bearer = auth_headers.get("Authorization", "")
        assert not bearer.startswith("Bearer ")

    def test_api_key_no_claude_code_identity_headers(self):
        """Regular API key must NOT inject Claude Code identity headers."""
        provider = AnthropicProvider(api_key=_FAKE_API_KEY, default_model="claude-sonnet-4-6")
        assert "x-app" not in provider.extra_headers
        user_agent = provider.extra_headers.get("user-agent", "")
        assert f"claude-cli/{_CLAUDE_CODE_VERSION}" not in user_agent

    def test_oauth_is_oauth_flag(self):
        provider = AnthropicProvider(api_key=_FAKE_OAUTH_TOKEN)
        assert provider._is_oauth is True

    def test_api_key_is_oauth_flag(self):
        provider = AnthropicProvider(api_key=_FAKE_API_KEY)
        assert provider._is_oauth is False


# ---------------------------------------------------------------------------
# Request payload tests: verify _build_kwargs produces correct content
# ---------------------------------------------------------------------------

class TestRequestPayload:
    def _make_oauth_kwargs(self, messages, tools=None, model="claude-sonnet-4-6"):
        provider = AnthropicProvider(api_key=_FAKE_OAUTH_TOKEN, default_model=model)
        return provider._build_kwargs(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=512,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=None,
            supports_caching=False,
        )

    def _make_api_key_kwargs(self, messages, tools=None, model="claude-sonnet-4-6"):
        provider = AnthropicProvider(api_key=_FAKE_API_KEY, default_model=model)
        return provider._build_kwargs(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=512,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice=None,
            supports_caching=False,
        )

    def test_oauth_beta_headers_in_extra_headers(self):
        """All required OAuth betas must be in extra_headers."""
        kwargs = self._make_oauth_kwargs([{"role": "user", "content": "hi"}])
        beta_str = kwargs["extra_headers"].get("anthropic-beta", "")
        betas = [b.strip() for b in beta_str.split(",")]
        for expected in _OAUTH_BETAS:
            assert expected in betas, f"Missing beta: {expected}"

    def test_oauth_no_interleaved_thinking_beta(self):
        """interleaved-thinking-2025-05-14 must NOT be present for opus-4-6/sonnet-4-6."""
        kwargs = self._make_oauth_kwargs([{"role": "user", "content": "hi"}])
        beta_str = kwargs["extra_headers"].get("anthropic-beta", "")
        assert "interleaved-thinking-2025-05-14" not in beta_str

    def test_oauth_prepends_claude_code_system_prompt_no_user_system(self):
        """Without user system prompt, only the CC identity block should appear."""
        kwargs = self._make_oauth_kwargs([{"role": "user", "content": "hi"}])
        system = kwargs.get("system", [])
        assert isinstance(system, list)
        assert len(system) == 1
        assert system[0]["text"] == _CLAUDE_CODE_SYSTEM_PROMPT

    def test_oauth_prepends_claude_code_system_prompt_with_user_system(self):
        """With user system prompt, CC identity block comes first."""
        messages = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "hi"},
        ]
        kwargs = self._make_oauth_kwargs(messages)
        system = kwargs.get("system", [])
        assert isinstance(system, list)
        assert system[0]["text"] == _CLAUDE_CODE_SYSTEM_PROMPT
        assert any(b.get("text") == "Be concise." for b in system)

    def test_api_key_no_claude_code_system_prompt(self):
        """Regular API key must NOT inject the CC system prompt."""
        kwargs = self._make_api_key_kwargs([{"role": "user", "content": "hi"}])
        system = kwargs.get("system")
        if system:
            texts = [b.get("text", "") for b in system if isinstance(b, dict)]
            assert _CLAUDE_CODE_SYSTEM_PROMPT not in texts

    def test_oauth_tool_names_normalized(self):
        """Tool names must be normalized to CC canonical casing in OAuth mode."""
        tools = [{"type": "function", "function": {
            "name": "read",
            "description": "read file",
            "parameters": {"type": "object", "properties": {}},
        }}]
        kwargs = self._make_oauth_kwargs([{"role": "user", "content": "hi"}], tools=tools)
        sent_tools = kwargs.get("tools", [])
        assert len(sent_tools) == 1
        assert sent_tools[0]["name"] == "Read"

    def test_api_key_tool_names_not_normalized(self):
        """In API key mode, tool names must be passed as-is."""
        tools = [{"type": "function", "function": {
            "name": "read",
            "description": "read file",
            "parameters": {"type": "object", "properties": {}},
        }}]
        kwargs = self._make_api_key_kwargs([{"role": "user", "content": "hi"}], tools=tools)
        sent_tools = kwargs.get("tools", [])
        assert len(sent_tools) == 1
        assert sent_tools[0]["name"] == "read"  # unchanged
