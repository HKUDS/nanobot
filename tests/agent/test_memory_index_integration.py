from unittest.mock import MagicMock

from nanobot.config.schema import MemoryIndexConfig


def test_context_builder_shows_pointer_note_when_enabled(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=True)
    prompt = ctx.build_system_prompt()
    assert "memory_search" in prompt
    assert "tool" in prompt.lower()
    # Full MEMORY.md content should NOT be inlined
    assert "Long-term Memory" not in prompt


def test_context_builder_loads_memory_file_when_disabled(tmp_path):
    from nanobot.agent.context import ContextBuilder

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("## Facts\n\nUser loves coffee.\n")
    ctx = ContextBuilder(tmp_path, memory_index_enabled=False)
    prompt = ctx.build_system_prompt()
    assert "User loves coffee" in prompt


async def test_agent_loop_registers_tool_when_enabled(tmp_path):
    # Must be async: AgentLoop.__init__ calls asyncio.create_task for startup_index
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    cfg = MemoryIndexConfig()
    cfg.enabled = True

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        memory_index_config=cfg,
    )
    assert loop.tools.get("memory_search") is not None


def test_agent_loop_does_not_register_tool_when_disabled(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        memory_index_config=MemoryIndexConfig(),  # enabled=False
    )
    assert loop.tools.get("memory_search") is None
