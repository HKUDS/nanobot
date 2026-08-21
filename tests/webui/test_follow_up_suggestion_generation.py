from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.session import webui_turns as wth
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui import follow_up_suggestions


@pytest.mark.asyncio
async def test_generation_bounds_recent_messages_and_normalized_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_message = " \n" + "x" * 4_100 + "\n "
    long_suggestion = "  Alpha \t Beta  " + "y" * 250
    provider = SimpleNamespace(
        chat=AsyncMock(
            return_value=LLMResponse(
                content="\n".join([
                    "SUGGESTION: /restart",
                    f"SUGGESTION: {long_suggestion}",
                    f"SUGGESTION: {long_suggestion}different only after the limit",
                    "SUGGESTION: Second",
                    "SUGGESTION: Third",
                    "SUGGESTION: Ignored fourth",
                ])
            )
        )
    )
    monkeypatch.setattr(follow_up_suggestions, "record_response_token_usage", lambda *_a, **_k: None)
    wth.remember_completed_websocket_turn_runtime(
        "chat-1",
        "turn-1",
        LLMRuntime(
            provider=cast(LLMProvider, provider),
            model="test-model",
            generation=GenerationSettings(),
            context_window_tokens=100_000,
        ),
    )

    suggestions = await follow_up_suggestions.generate_follow_up_suggestions(
        config=Config.model_validate({"followUpSuggestions": {"enabled": True}}),
        payload={
            "chat_id": "chat-1",
            "turn_id": "turn-1",
            "messages": [
                {"role": "user", "content": "discarded"},
                {"role": "assistant", "content": "one"},
                {"role": "user", "content": "two"},
                {"role": "assistant", "content": "three"},
                {"role": "user", "content": "four"},
                {"role": "assistant", "content": "five"},
                {"role": "user", "content": long_message},
            ],
        },
    )

    sent_messages = provider.chat.await_args.args[0]
    assert [message["content"] for message in sent_messages[:-1]] == [
        "one",
        "two",
        "three",
        "four",
        "five",
        "x" * 4_000,
    ]
    assert sent_messages[-1]["role"] == "user"
    assert "SUGGESTION:" in sent_messages[-1]["content"]
    assert suggestions == [
        ("Alpha Beta " + "y" * 250)[:200],
        "Second",
        "Third",
    ]


@pytest.mark.asyncio
async def test_generation_places_format_request_after_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def respond(messages: list[dict[str, object]], **_kwargs: object) -> LLMResponse:
        if "SUGGESTION:" in str(messages[-1]["content"]):
            return LLMResponse(
                content="SUGGESTION: Ask for an example\nSUGGESTION: Explain it simply"
            )
        return LLMResponse(content="A normal assistant reply instead of the line protocol")

    provider = SimpleNamespace(
        chat=AsyncMock(side_effect=respond)
    )
    record_usage = Mock()
    monkeypatch.setattr(follow_up_suggestions, "record_response_token_usage", record_usage)
    wth.remember_completed_websocket_turn_runtime(
        "chat-ordering",
        "turn-ordering",
        LLMRuntime(
            provider=cast(LLMProvider, provider),
            model="test-model",
            generation=GenerationSettings(),
            context_window_tokens=100_000,
        ),
    )

    suggestions = await follow_up_suggestions.generate_follow_up_suggestions(
        config=Config.model_validate({"followUpSuggestions": {"enabled": True}}),
        payload={
            "chat_id": "chat-ordering",
            "turn_id": "turn-ordering",
            "messages": [{"role": "user", "content": "Explain this concept"}],
        },
    )

    assert suggestions == ["Ask for an example", "Explain it simply"]
    assert provider.chat.await_count == 1
    assert record_usage.call_count == 1
