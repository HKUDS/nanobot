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
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.providers.image_generation import GeneratedImageResponse

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
async def test_generated_image_media_is_attached_to_final_assistant_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.OpenRouterImageGenerationClient",
        FakeImageClient,
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
    assert len(result.media) == 1
    assert Path(result.media[0]).is_file()

    session = loop.sessions.get_or_create("websocket:chat-image")
    assert session.messages[-1]["role"] == "assistant"
    assert session.messages[-1]["media"] == result.media
