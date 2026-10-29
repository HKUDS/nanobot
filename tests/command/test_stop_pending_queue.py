"""Slash stop shares the real session cancellation owner and frees its inbox."""

import asyncio
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import cmd_stop
from nanobot.command.router import CommandContext
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.runtime_context import public_history_message


class _Provider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(provider_name="test")
        self.started = asyncio.Event()
        self.calls = 0

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            await asyncio.Event().wait()
        return LLMResponse(content="next turn completed", finish_reason="stop")


def _message(content: str) -> InboundMessage:
    return InboundMessage(channel="cli", sender_id="user", chat_id="stop-test", content=content)


def _context(loop: AgentLoop) -> CommandContext:
    message = _message("/stop")
    return CommandContext(msg=message, session=None, key=message.session_key, raw="/stop", loop=loop)


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_count", [0, 2])
async def test_cmd_stop_cancels_work_and_next_turn_uses_a_fresh_inbox(tmp_path, pending_count):
    provider = _Provider()
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    try:
        await loop._dispatch_inbound(_message("first turn"))
        await asyncio.wait_for(provider.started.wait(), 3)
        for index in range(pending_count):
            await loop._dispatch_inbound(_message(f"discard followup {index}"))

        result = await cmd_stop(_context(loop))

        assert result.content == "Stopped 1 task(s)."
        assert provider.calls == 1
        await loop._dispatch_inbound(_message("next turn"))
        await asyncio.wait_for(asyncio.gather(*tuple(loop._active_tasks["cli:stop-test"])), 3)
        saved = await loop.sessions.state.read("cli:stop-test")
        assert saved is not None
        users = [public_history_message(row)["content"] for row in saved.messages if row["role"] == "user"]
        assert users == ["first turn", "next turn"]
        assert provider.calls == 2
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_cmd_stop_idle_does_not_create_a_session(tmp_path):
    loop = AgentLoop(bus=MessageBus(), provider=_Provider(), workspace=tmp_path)
    try:
        result = await cmd_stop(_context(loop))
        assert result.content == "No active task to stop."
        assert await loop.sessions.state.list_sessions() == []
    finally:
        await loop.aclose()
