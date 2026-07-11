from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import set_config_path
from nanobot.config.schema import ImageGenerationToolConfig, ProviderConfig, ToolsConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.image_generation import GeneratedImageResponse
from nanobot.runtime_context import public_history_message

PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeImageClient:
    def __init__(self, **kwargs: Any) -> None:
        pass

    async def generate(self, **kwargs: Any) -> GeneratedImageResponse:
        return GeneratedImageResponse(images=[PNG_DATA_URL], content="", raw={})


@pytest.mark.asyncio
async def test_outbound_no_longer_carries_generated_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Media delivery is now the LLM's responsibility via the message tool."""
    set_config_path(tmp_path / "config.json")
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.get_image_gen_provider",
        lambda name: FakeImageClient if name == "openrouter" else None,
    )
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    provider.chat_with_retry = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCallRequest(
                        id="call_img",
                        name="generate_image",
                        arguments={"prompt": "draw a tiny icon"},
                    )
                ],
            ),
            LLMResponse(content="Done", finish_reason="stop"),
        ]
    )
    provider.chat_stream_with_retry = AsyncMock()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        tools_config=ToolsConfig(
            image_generation=ImageGenerationToolConfig(enabled=True),
        ),
        image_generation_provider_config=ProviderConfig(api_key="sk-or-test"),
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

    result = await loop._process_message(
        InboundMessage(
            channel="websocket",
            sender_id="user",
            chat_id="chat-image",
            content="draw an icon",
        )
    )

    assert result is not None
    assert result.content == "Done"
    # OutboundMessage no longer carries generated media —
    # the LLM sends images via the message tool instead.
    assert result.media == []


@pytest.mark.asyncio
async def test_image_mode_instruction_is_persisted_as_next_turn_prefix(tmp_path: Path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="first answer"),
        LLMResponse(content="second answer"),
    ])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        tools_config=ToolsConfig(
            image_generation=ImageGenerationToolConfig(enabled=True),
        ),
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)

    await loop._process_message(InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-image-prefix",
        content="draw a fox",
        metadata={
            "image_generation": {
                "enabled": True,
                "aspect_ratio": "16:9",
            },
        },
    ))
    await loop._process_message(InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-image-prefix",
        content="thanks",
    ))

    first_wire = LLMProvider._sanitize_empty_content(
        provider.chat_with_retry.await_args_list[0].kwargs["messages"]
    )
    second_wire = LLMProvider._sanitize_empty_content(
        provider.chat_with_retry.await_args_list[1].kwargs["messages"]
    )
    assert second_wire[: len(first_wire)] == first_wire
    assert "aspect_ratio='16:9'" in first_wire[1]["content"]

    persisted = loop.sessions.get_or_create("websocket:chat-image-prefix").messages[0]
    assert persisted["content"] == first_wire[1]["content"]
    assert public_history_message(persisted)["content"] == "draw a fox"
