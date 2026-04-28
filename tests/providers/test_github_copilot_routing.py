"""Regression tests for GitHub Copilot /responses routing.

Covers the Copilot-specific branches added to route GPT-5 / o-series models
through the /responses endpoint without falling back to /chat/completions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def _make_copilot_provider() -> OpenAICompatProvider:
    """Build a bare provider with the real github_copilot spec (no network)."""
    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    p.default_model = "github_copilot/gpt-5.4-mini"
    p._spec = find_by_name("github_copilot")
    p._effective_base = "https://api.githubcopilot.com"
    p._responses_failures = {}
    p._responses_tripped_at = {}
    return p


def test_should_use_responses_api_allows_github_copilot_non_openai_base():
    """github_copilot bypasses the direct-OpenAI base check and still opts in for GPT-5."""
    provider = _make_copilot_provider()
    assert provider._should_use_responses_api("github_copilot/gpt-5.4-mini", None) is True
    assert provider._should_use_responses_api("github_copilot/o3", None) is True


def test_build_responses_body_strips_github_copilot_prefix():
    """/responses body must send the bare model name; gateway rejects routing prefixes."""
    provider = _make_copilot_provider()
    body = provider._build_responses_body(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="github_copilot/gpt-5.4-mini",
        max_tokens=16,
        temperature=0.1,
        reasoning_effort=None,
        tool_choice=None,
    )
    assert body["model"] == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_github_copilot_does_not_fall_back_from_responses_error():
    """On /responses failure, github_copilot must re-raise instead of hitting /chat/completions."""
    from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

    mock_client = MagicMock()
    mock_client.api_key = "no-key"

    class _CompatError(Exception):
        """Looks like a fallback-eligible error on other providers."""
        status_code = 400
        body = "Unsupported parameter responses api"

    mock_client.responses.create = AsyncMock(side_effect=_CompatError("boom"))
    mock_client.chat.completions.create = AsyncMock()

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI", return_value=mock_client):
        provider = GitHubCopilotProvider(default_model="github_copilot/gpt-5.4-mini")
    provider._get_copilot_access_token = AsyncMock(return_value="copilot-access-token")

    response = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="github_copilot/gpt-5.4-mini",
        max_tokens=16,
        temperature=0.1,
    )

    assert response.finish_reason == "error"
    mock_client.responses.create.assert_awaited_once()
    mock_client.chat.completions.create.assert_not_awaited()
