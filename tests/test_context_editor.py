"""Tests for prompt budgeting and pre-send context editing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ContextEditingConfig
from nanobot.providers.base import LLMResponse


def test_context_editor_compacts_old_tool_results_and_strips_thinking() -> None:
    from nanobot.agent.context_editor import ContextEditor

    config = ContextEditingConfig(
        enabled=True,
        max_prompt_tokens=10_000,
        keep_recent_messages=4,
        keep_recent_tool_messages=1,
        max_tool_chars=48,
    )
    editor = ContextEditor(config)
    recent_tool_content = "recent-tool\n" + ("B" * 120)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user-1"},
        {
            "role": "assistant",
            "content": "thinking...",
            "reasoning_content": "private chain of thought",
            "thinking_blocks": [{"type": "thinking", "thinking": "internal"}],
        },
        {"role": "tool", "name": "read_file", "tool_call_id": "call-1", "content": "old-tool\n" + ("A" * 120)},
        {"role": "assistant", "content": "done-1"},
        {"role": "user", "content": "user-2"},
        {"role": "assistant", "content": "call tool"},
        {"role": "tool", "name": "read_file", "tool_call_id": "call-2", "content": recent_tool_content},
        {"role": "assistant", "content": "done-2"},
    ]

    prepared = editor.prepare(messages)
    tool_messages = [msg for msg in prepared if msg["role"] == "tool"]

    assert len(tool_messages) == 2
    assert tool_messages[0]["content"].startswith("[context-edited tool result: read_file]")
    assert "old-tool" in tool_messages[0]["content"]
    assert tool_messages[1]["content"] == recent_tool_content
    assert all("reasoning_content" not in msg for msg in prepared)
    assert all("thinking_blocks" not in msg for msg in prepared)


def test_context_editor_drops_oldest_turns_to_fit_budget() -> None:
    from nanobot.agent.context_editor import ContextEditor

    config = ContextEditingConfig(
        enabled=True,
        max_prompt_tokens=120,
        keep_recent_messages=4,
        keep_recent_tool_messages=1,
        max_tool_chars=32,
    )
    editor = ContextEditor(config)
    messages = [{"role": "system", "content": "system " * 20}]
    for idx in range(5):
        messages.extend([
            {"role": "user", "content": f"user-{idx} " + ("U" * 90)},
            {"role": "assistant", "content": f"assistant-{idx} " + ("A" * 90)},
        ])

    prepared = editor.prepare(messages)
    prepared_users = [msg["content"] for msg in prepared if msg["role"] == "user"]

    assert editor.estimate_tokens(prepared) <= config.max_prompt_tokens
    assert any("user-4" in content for content in prepared_users)
    assert messages[1]["content"] not in prepared_users


def test_agent_loop_applies_context_editor_before_provider_call(tmp_path) -> None:
    async def _run() -> None:
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat = AsyncMock(return_value=LLMResponse(content="final"))

        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            context_editing=ContextEditingConfig(
                enabled=True,
                max_prompt_tokens=140,
                keep_recent_messages=4,
                keep_recent_tool_messages=1,
                max_tool_chars=40,
            ),
        )

        initial_messages = [
            {"role": "system", "content": "system " * 20},
            {"role": "user", "content": "user-1 " + ("U" * 90)},
            {"role": "assistant", "content": "assistant-1 " + ("A" * 90)},
            {"role": "tool", "name": "read_file", "tool_call_id": "call-1", "content": "tool-1 " + ("T" * 200)},
            {"role": "assistant", "content": "assistant-2 " + ("B" * 90)},
            {"role": "user", "content": "user-2 " + ("V" * 90)},
        ]

        final_content, _, _ = await loop._run_agent_loop(initial_messages)
        sent_messages = provider.chat.await_args.kwargs["messages"]
        estimate = loop.context_editor.estimate_tokens(sent_messages)

        assert final_content == "final"
        assert estimate <= loop.context_editing.max_prompt_tokens
        assert all(msg.get("content") != initial_messages[1]["content"] for msg in sent_messages)

    asyncio.run(_run())
