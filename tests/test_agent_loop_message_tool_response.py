from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


def _make_loop(tmp_path: Path, *, suppress: bool = True) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        suppress_final_response_if_message_tool=suppress,
    )


def _logger_messages(mock: MagicMock) -> list[str]:
    msgs: list[str] = []
    for call in mock.call_args_list:
        if call.args and isinstance(call.args[0], str):
            msgs.append(call.args[0])
    return msgs


@pytest.mark.asyncio
async def test_message_tool_usage_suppresses_final_response_with_explicit_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path, suppress=True)

    async def _fake_run_agent_loop(initial_messages, on_progress=None):
        message_tool = loop.tools.get("message")
        assert isinstance(message_tool, MessageTool)
        message_tool._sent_in_turn = True
        return "Final answer", [], initial_messages

    monkeypatch.setattr(loop, "_run_agent_loop", _fake_run_agent_loop)
    info_mock = MagicMock()
    debug_mock = MagicMock()
    monkeypatch.setattr("nanobot.agent.loop.logger.info", info_mock)
    monkeypatch.setattr("nanobot.agent.loop.logger.debug", debug_mock)

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="c1", content="hello")
    )

    assert response is None
    messages = _logger_messages(info_mock)
    assert "Response suppressed due to message tool usage in this turn." in messages
    assert "Sending response to {}:{}: {}" not in messages
    assert "Response to {}:{}: {}" not in messages
    assert debug_mock.called


@pytest.mark.asyncio
async def test_message_tool_usage_can_still_send_final_response_when_suppression_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path, suppress=False)

    async def _fake_run_agent_loop(initial_messages, on_progress=None):
        message_tool = loop.tools.get("message")
        assert isinstance(message_tool, MessageTool)
        message_tool._sent_in_turn = True
        return "Final answer", [], initial_messages

    monkeypatch.setattr(loop, "_run_agent_loop", _fake_run_agent_loop)
    info_mock = MagicMock()
    monkeypatch.setattr("nanobot.agent.loop.logger.info", info_mock)

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="c1", content="hello")
    )

    assert response is not None
    assert response.content == "Final answer"
    messages = _logger_messages(info_mock)
    assert "Response suppressed due to message tool usage in this turn." not in messages
    assert "Message tool was used in this turn, but final response delivery is enabled." in messages
    assert "Sending response to {}:{}: {}" in messages
    assert "Response to {}:{}: {}" not in messages


@pytest.mark.asyncio
async def test_normal_turn_without_message_tool_usage_behaves_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path, suppress=True)

    async def _fake_run_agent_loop(initial_messages, on_progress=None):
        return "Final answer", [], initial_messages

    monkeypatch.setattr(loop, "_run_agent_loop", _fake_run_agent_loop)
    info_mock = MagicMock()
    monkeypatch.setattr("nanobot.agent.loop.logger.info", info_mock)

    response = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="c1", content="hello")
    )

    assert response is not None
    assert response.content == "Final answer"
    messages = _logger_messages(info_mock)
    assert "Sending response to {}:{}: {}" in messages
    assert "Response suppressed due to message tool usage in this turn." not in messages
    assert "Response to {}:{}: {}" not in messages

