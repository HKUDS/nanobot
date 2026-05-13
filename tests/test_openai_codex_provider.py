import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from nanobot.providers.openai_codex_provider import (
    OpenAICodexProvider,
    _normalize_tool_choice,
)


def test_normalize_tool_choice_flattens_openai_function_shape() -> None:
    assert _normalize_tool_choice(
        {"type": "function", "function": {"name": "save_memory"}}
    ) == {"type": "function", "name": "save_memory"}


def test_normalize_tool_choice_keeps_flat_function_shape() -> None:
    assert _normalize_tool_choice({"type": "function", "name": "save_memory"}) == {
        "type": "function",
        "name": "save_memory",
    }


def test_codex_provider_sends_flattened_tool_choice() -> None:
    captured: dict[str, object] = {}

    async def fake_request_codex(url, headers, body, verify):
        captured["body"] = body
        return "ok", [], "stop"

    async def run() -> None:
        provider = OpenAICodexProvider(default_model="openai-codex/gpt-5.4")
        with (
            patch(
                "nanobot.providers.openai_codex_provider.get_codex_token",
                return_value=SimpleNamespace(account_id="acct_123", access="token_123"),
            ),
            patch(
                "nanobot.providers.openai_codex_provider._request_codex",
                side_effect=fake_request_codex,
            ),
        ):
            response = await provider.chat(
                messages=[{"role": "user", "content": "hello"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "save_memory",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": "save_memory"}},
            )

        assert response.finish_reason == "stop"

    asyncio.run(run())

    assert captured["body"]["tool_choice"] == {"type": "function", "name": "save_memory"}
