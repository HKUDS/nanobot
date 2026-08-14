import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

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
    long_suggestion = "  Alpha \n Beta  " + "y" * 250
    provider = SimpleNamespace(
        chat=AsyncMock(
            return_value=LLMResponse(
                content=json.dumps([
                    "/restart",
                    long_suggestion,
                    long_suggestion + "different only after the limit",
                    42,
                    "Second",
                    "Third",
                    "Ignored fourth",
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
    assert [message["content"] for message in sent_messages[1:]] == [
        "one",
        "two",
        "three",
        "four",
        "five",
        "x" * 4_000,
    ]
    assert suggestions == [
        ("Alpha Beta " + "y" * 250)[:200],
        "Second",
        "Third",
    ]
