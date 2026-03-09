from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig
from nanobot.providers.base import LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import _consume_sse


class _FakeSSELikeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamingProvider:
    def get_default_model(self) -> str:
        return "openai-codex/gpt-5.1-codex"

    async def chat(self, *args, **kwargs) -> LLMResponse:
        on_text_delta = kwargs.get("on_text_delta")
        if on_text_delta:
            await on_text_delta("Hel")
            await on_text_delta("lo")
        return LLMResponse(content="Hello", streamed_output=True)


def _make_agent_loop(provider):
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("nanobot.agent.loop.ContextBuilder") as mock_context_builder,
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr,
    ):
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        mock_context = mock_context_builder.return_value
        mock_context.add_assistant_message.side_effect = (
            lambda messages, content, *args, **kwargs: messages + [{"role": "assistant", "content": content}]
        )
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    loop.context_editor = SimpleNamespace(prepare=lambda messages: messages)
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_codex_sse_forwards_text_deltas() -> None:
    deltas: list[str] = []

    async def _on_text_delta(delta: str) -> None:
        deltas.append(delta)

    response = _FakeSSELikeResponse(
        [
            'data: {"type":"response.output_text.delta","delta":"Hel"}',
            "",
            'data: {"type":"response.output_text.delta","delta":"lo"}',
            "",
            'data: {"type":"response.completed","response":{"status":"completed"}}',
            "",
        ]
    )

    content, tool_calls, finish_reason, streamed_output = await _consume_sse(
        response,
        on_text_delta=_on_text_delta,
    )

    assert content == "Hello"
    assert tool_calls == []
    assert finish_reason == "stop"
    assert streamed_output is True
    assert deltas == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_agent_loop_emits_replace_progress_for_streamed_text() -> None:
    loop = _make_agent_loop(_StreamingProvider())
    progress_calls: list[tuple[str, bool]] = []

    async def _on_progress(content: str, *, replace: bool = False, tool_hint: bool = False) -> None:
        assert tool_hint is False
        progress_calls.append((content, replace))

    final_content, _, _ = await loop._run_agent_loop(
        [{"role": "user", "content": "hello"}],
        on_progress=_on_progress,
        stream_text_progress=True,
    )

    assert final_content == "Hello"
    assert progress_calls == [("Hel", True), ("Hello", True)]


@pytest.mark.asyncio
async def test_litellm_provider_streams_text_deltas() -> None:
    provider = LiteLLMProvider(api_key="test", default_model="openai/gpt-4o-mini")
    deltas: list[str] = []

    async def _on_text_delta(delta: str) -> None:
        deltas.append(delta)

    async def _fake_acompletion(**kwargs):
        if kwargs.get("stream"):
            async def _gen():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))]
                )
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))]
                )
            return _gen()
        raise AssertionError("expected streaming path")

    built_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Hello", tool_calls=None), finish_reason="stop")],
        usage=None,
    )

    with (
        patch("nanobot.providers.litellm_provider.acompletion", new=_fake_acompletion),
        patch("nanobot.providers.litellm_provider.litellm.stream_chunk_builder", return_value=built_response),
    ):
        response = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            on_text_delta=_on_text_delta,
        )

    assert deltas == ["Hel", "lo"]
    assert response.content == "Hello"
    assert response.streamed_output is True


@pytest.mark.asyncio
async def test_telegram_reuses_draft_message_for_streaming_reply() -> None:
    channel = TelegramChannel(TelegramConfig(enabled=True, token="test"), MessageBus())
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)),
        edit_message_text=AsyncMock(return_value=True),
        delete_message=AsyncMock(return_value=True),
        send_photo=AsyncMock(),
        send_voice=AsyncMock(),
        send_audio=AsyncMock(),
        send_document=AsyncMock(),
    )
    channel._app = SimpleNamespace(bot=bot)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="Hel",
            metadata={"_progress": True, "_progress_mode": "replace"},
        )
    )
    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="Hello",
            metadata={"_progress": True, "_progress_mode": "replace"},
        )
    )
    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="Hello world",
        )
    )

    assert bot.send_message.await_count == 1
    assert bot.edit_message_text.await_count == 2
    assert bot.delete_message.await_count == 0
