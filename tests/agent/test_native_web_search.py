from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_agent_loop_skips_builtin_web_search_when_provider_uses_native(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "openai-codex/gpt-5.1-codex"
    provider.uses_native_web_search.return_value = True

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr:
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)

    assert loop.tools.has("web_search") is False
    assert loop.tools.has("web_fetch") is True


@pytest.mark.asyncio
async def test_subagent_skips_builtin_web_search_when_provider_uses_native(tmp_path):
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "openai-codex/gpt-5.1-codex"
    provider.uses_native_web_search.return_value = True

    bus = MessageBus()
    mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

    captured_tools = {}

    async def fake_chat_with_retry(*, messages, tools, model):
        captured_tools["names"] = [
            tool.get("name") or tool.get("function", {}).get("name")
            for tool in tools
            if (tool.get("name") or tool.get("function", {}).get("name"))
        ]
        return MagicMock(has_tool_calls=False, content="done")

    provider.chat_with_retry = fake_chat_with_retry
    mgr._announce_result = AsyncMock(return_value=None)

    await mgr._run_subagent("task1", "do work", "label", {"channel": "cli", "chat_id": "direct"})

    assert "web_search" not in captured_tools["names"]
    assert "web_fetch" in captured_tools["names"]
