"""Tests for LM1-C hook registration and runtime canvas injection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.layered_memory import LayeredMemoryFacade
from nanobot.agent.layered_memory.offload.hook import LayeredMemoryHook
from nanobot.agent.layered_memory.offload.node_registry import NodeRegistry
from nanobot.config.schema import LayeredMemoryConfig
from nanobot.providers.base import LLMResponse, ToolCallRequest


@pytest.mark.asyncio
async def test_layered_memory_hook_syncs_nodes_and_refreshes(tmp_path: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    facade = LayeredMemoryFacade(tmp_path, cfg)
    hook = LayeredMemoryHook(facade, "sess", is_subagent=False)
    context = AgentHookContext(
        iteration=0,
        messages=[],
        tool_calls=[
            ToolCallRequest(id="call_1", name="grep", arguments={"pattern": "x"}),
        ],
        tool_results=["line one\nline two"],
    )
    await hook.after_tools(context)
    registry = NodeRegistry(tmp_path, "sess")
    node = registry.get("call_1")
    assert node is not None
    assert node.tool == "grep"
    assert (tmp_path / ".nanobot" / "canvas" / "sess" / "canvas.mmd").exists()


@pytest.mark.asyncio
async def test_loop_runtime_lines_include_task_canvas(tmp_path: Path) -> None:
    from tests.agent.conftest import make_loop

    loop = make_loop(
        tmp_path,
        patch_deps=True,
        provider=MagicMock(),
        tools_config=MagicMock(),
    )
    loop._layered_memory = LayeredMemoryConfig(enable=True)
    loop._layered_memory.offload.enable = True
    loop._layered_memory_facade = LayeredMemoryFacade(tmp_path, loop._layered_memory)
    loop._layered_memory_facade.register_tool_result(
        session_key="cli:direct",
        node_id="call_a",
        tool_name="read_file",
        persist_path="p.txt",
        summary="read docs",
        chars=100,
    )

    lines = await loop._layered_memory_runtime_lines("cli:direct", "read docs")
    joined = "\n".join(lines)
    assert "[Task canvas]" in joined
    assert "read_file" in joined


@pytest.mark.asyncio
async def test_run_agent_loop_registers_layered_memory_hook(tmp_path: Path) -> None:
    from tests.agent.conftest import make_loop

    loop = make_loop(
        tmp_path,
        patch_deps=True,
        provider=MagicMock(),
        tools_config=MagicMock(),
    )
    loop._layered_memory = LayeredMemoryConfig(enable=True)
    loop._layered_memory.offload.enable = True
    loop._layered_memory_facade = LayeredMemoryFacade(tmp_path, loop._layered_memory)

    captured_hooks: list = []

    async def fake_run(spec):
        captured_hooks.append(spec.hook)
        return MagicMock(
            final_content="ok",
            messages=spec.initial_messages,
            tools_used=[],
            stop_reason="completed",
        )

    with patch.object(loop.runner, "run", new=fake_run):
        await loop._run_agent_loop(
            [{"role": "user", "content": "hi"}],
            session_key="cli:direct",
            is_subagent=False,
        )

    assert captured_hooks
    hook = captured_hooks[0]
    assert hook.__class__.__name__ == "CompositeHook"
    assert any(h.__class__.__name__ == "LayeredMemoryHook" for h in hook._hooks)


@pytest.mark.asyncio
async def test_build_initial_messages_injects_canvas(tmp_path: Path) -> None:
    from nanobot.agent.context import ContextBuilder
    from nanobot.bus.events import InboundMessage
    from nanobot.session.manager import Session
    from tests.agent.conftest import make_loop

    loop = make_loop(
        tmp_path,
        patch_deps=True,
        provider=MagicMock(),
        tools_config=MagicMock(),
    )
    loop._layered_memory = LayeredMemoryConfig(enable=True)
    loop._layered_memory.offload.enable = True
    loop._layered_memory_facade = LayeredMemoryFacade(tmp_path, loop._layered_memory)
    loop.context = ContextBuilder(tmp_path)
    loop._layered_memory_facade.register_tool_result(
        session_key="cli:direct",
        node_id="n1",
        tool_name="exec",
        persist_path=None,
        summary="ran tests",
        chars=10,
    )

    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="hello")
    session = Session(key="cli:direct")
    runtime_lines = list(await loop._layered_memory_runtime_lines("cli:direct", "hello"))
    messages = loop._build_initial_messages(
        msg,
        session,
        [],
        None,
        runtime_lines=runtime_lines,
    )
    user_content = str(messages[-1]["content"])
    assert "[Task canvas]" in user_content
