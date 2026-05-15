from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.providers.openai_codex_provider import OpenAICodexProvider


@pytest.mark.asyncio
async def test_codex_prompt_cache_key_uses_stable_conversation_prefix(monkeypatch) -> None:
    bodies: list[dict] = []

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda: SimpleNamespace(account_id="acct", access="token"),
    )

    async def fake_request(url, headers, body, verify, on_content_delta=None):
        bodies.append(body)
        return "ok", [], "stop"

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", fake_request)

    provider = OpenAICodexProvider()
    await provider.chat(
        [
            {"role": "system", "content": "You are nanobot."},
            {"role": "user", "content": "first request"},
            {"role": "assistant", "content": "first answer"},
        ],
    )
    await provider.chat(
        [
            {"role": "system", "content": "You are nanobot."},
            {"role": "user", "content": "first request"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "follow up"},
        ],
    )
    await provider.chat(
        [
            {"role": "system", "content": "You are nanobot."},
            {"role": "user", "content": "different request"},
            {"role": "assistant", "content": "first answer"},
        ],
    )

    assert bodies[0]["prompt_cache_key"] == bodies[1]["prompt_cache_key"]
    assert bodies[0]["prompt_cache_key"] != bodies[2]["prompt_cache_key"]
