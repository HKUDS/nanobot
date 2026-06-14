"""Tests for subagent tool registration and wiring."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_subagent_exec_tool_receives_allowed_env_keys(tmp_path):
    """allowed_env_keys from ExecToolConfig must be forwarded to the subagent's ExecTool."""
    from nanobot.agent.subagent import SubagentManager, SubagentStatus
    from nanobot.agent.tools.shell import ExecToolConfig
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ToolsConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        tools_config=ToolsConfig(exec=ExecToolConfig(allowed_env_keys=["GOPATH", "JAVA_HOME"])),
    )
    mgr._announce_result = AsyncMock()

    async def fake_run(spec):
        exec_tool = spec.tools.get("exec")
        assert exec_tool is not None
        assert exec_tool.allowed_env_keys == ["GOPATH", "JAVA_HOME"]
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_subagent_uses_configured_max_iterations(tmp_path):
    """Subagents should honor the configured tool-iteration limit."""
    from nanobot.agent.subagent import SubagentManager, SubagentStatus
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_iterations=37,
    )
    mgr._announce_result = AsyncMock()

    async def fake_run(spec):
        assert spec.max_iterations == 37
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_spawn_forwards_temperature_to_run_spec(tmp_path):
    """A temperature passed to spawn() should reach the AgentRunSpec."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._announce_result = AsyncMock()

    seen = {}

    async def fake_run(spec):
        seen["temperature"] = spec.temperature
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    await mgr.spawn(task="do task", temperature=0.9)
    await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)

    assert seen["temperature"] == 0.9


@pytest.mark.asyncio
async def test_spawn_tool_rejects_when_at_concurrency_limit(tmp_path):
    """SpawnTool should return an error string when the concurrency limit is reached."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.spawn import SpawnTool
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._announce_result = AsyncMock()

    # Block the first subagent so it stays "running"
    release = asyncio.Event()

    async def fake_run(spec):
        await release.wait()
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    from nanobot.agent.tools.context import RequestContext

    tool = SpawnTool(mgr)
    tool.set_context(RequestContext(channel="test", chat_id="c1", session_key="test:c1"))

    # First spawn succeeds
    result = await tool.execute(task="first task")
    assert "started" in result

    # Second spawn should be rejected (default limit is 1)
    result = await tool.execute(task="second task")
    assert "Cannot spawn subagent" in result
    assert "concurrency limit reached" in result

    # Release the first subagent
    release.set()
    # Allow cleanup
    await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)


def test_subagent_default_max_concurrent_matches_agent_defaults(tmp_path):
    """Direct SubagentManager construction should use the agent default concurrency limit."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    assert mgr.max_concurrent_subagents == AgentDefaults().max_concurrent_subagents


def test_subagent_default_max_iterations_matches_agent_defaults(tmp_path):
    """Direct SubagentManager construction should use the agent default limit."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    assert mgr.max_iterations == AgentDefaults().max_tool_iterations


def test_agent_loop_passes_max_iterations_to_subagents(tmp_path):
    """AgentLoop's configured limit should be shared with spawned subagents."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        max_iterations=42,
    )

    assert loop.subagents.max_iterations == 42


@pytest.mark.asyncio
async def test_agent_loop_syncs_updated_max_iterations_before_run(tmp_path):
    """Runtime max_iterations changes should be reflected before tool execution."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        max_iterations=42,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    async def fake_run(spec):
        assert spec.max_iterations == 55
        assert loop.subagents.max_iterations == 55
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_run)
    loop.max_iterations = 55

    await loop._run_agent_loop([])

    loop.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_drain_pending_blocks_while_subagents_running(tmp_path):
    """_drain_pending should block when no messages are available but sub-agents are still running."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.session.manager import Session

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
    session = Session(key="test:drain-block")
    injection_callback = None

    # Capture the injection_callback that _run_agent_loop creates
    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback

        # Simulate: first call to injection_callback should block because
        # sub-agents are running and no messages are in the queue yet.
        # We'll resolve this from a concurrent task.
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    # Register a running sub-agent in the SubagentManager for this session
    async def _hang_forever():
        await asyncio.Event().wait()

    hang_task = asyncio.create_task(_hang_forever())
    loop.subagents._session_tasks.setdefault(session.key, set()).add("sub-drain-1")
    loop.subagents._running_tasks["sub-drain-1"] = hang_task

    # Run _run_agent_loop — this defines the _drain_pending closure
    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=session,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # Now test the callback directly
    # With sub-agents running and an empty queue, it should block
    drain_task = asyncio.create_task(injection_callback())

    # Let the task enter the blocking queue wait.
    await asyncio.sleep(0)

    # Should still be running (blocked on pending_queue.get())
    assert not drain_task.done(), "drain should block while sub-agents are running"

    # Now put a message in the queue (simulating sub-agent completion)
    await pending_queue.put(InboundMessage(
        sender_id="subagent",
        channel="test",
        chat_id="c1",
        content="Sub-agent result",
        media=None,
        metadata={},
    ))

    # Should unblock and return results
    results = await asyncio.wait_for(drain_task, timeout=2.0)
    assert len(results) >= 1
    assert results[0]["role"] == "user"
    assert "Sub-agent result" in str(results[0]["content"])

    # Cleanup
    hang_task.cancel()
    try:
        await hang_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_drain_pending_no_block_when_no_subagents(tmp_path):
    """_drain_pending should not block when no sub-agents are running."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue = asyncio.Queue()
    injection_callback = None

    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=None,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # With no sub-agents and empty queue, should return immediately
    results = await asyncio.wait_for(injection_callback(), timeout=1.0)
    assert results == []


@pytest.mark.asyncio
async def test_drain_pending_timeout(tmp_path):
    """_drain_pending should return empty after timeout when sub-agents hang."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.session.manager import Session

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue = asyncio.Queue()
    session = Session(key="test:drain-timeout")
    injection_callback = None

    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    # Register a "running" sub-agent that will never complete
    async def _hang_forever():
        await asyncio.Event().wait()

    hang_task = asyncio.create_task(_hang_forever())
    loop.subagents._session_tasks.setdefault(session.key, set()).add("sub-timeout-1")
    loop.subagents._running_tasks["sub-timeout-1"] = hang_task

    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=session,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # Patch the timeout path without leaking the queue.get() coroutine.
    async def _timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    with patch("nanobot.agent.loop.asyncio.wait_for", side_effect=_timeout):
        results = await injection_callback()
        assert results == []

    hang_task.cancel()
    try:
        await hang_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_spawn_with_model_preset_uses_different_model(tmp_path):
    """Specifying model_preset should cause the subagent to use that preset's model/provider."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ModelPresetConfig
    from nanobot.providers.factory import ProviderSnapshot

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "default-model"

    preset_cfg = ModelPresetConfig(
        model="preset-model",
        provider="auto",
        max_tokens=4096,
        temperature=0.5,
    )
    preset_provider = MagicMock()
    preset_provider.generation = SimpleNamespace(
        temperature=0.5, max_tokens=4096, reasoning_effort=None,
    )
    snapshot = ProviderSnapshot(
        provider=preset_provider,
        model="preset-model",
        context_window_tokens=32768,
        signature=("test",),
    )

    def fake_loader(name):
        assert name == "fast"
        return snapshot

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        spawn_presets={"fast": preset_cfg},
        preset_snapshot_loader=fake_loader,
    )
    mgr._announce_result = AsyncMock()

    seen = {}

    async def fake_run(spec):
        seen["model"] = spec.model
        seen["temperature"] = spec.temperature
        seen["max_tokens"] = spec.max_tokens
        seen["context_window_tokens"] = spec.context_window_tokens
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[],
        )

    with patch.object(AgentRunner, "run", AsyncMock(side_effect=fake_run)):
        await mgr.spawn(task="do task", model_preset="fast")
        await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)

    assert seen["model"] == "preset-model"
    assert seen["temperature"] == 0.5
    assert seen["max_tokens"] == 4096
    assert seen["context_window_tokens"] == 32768


@pytest.mark.asyncio
async def test_spawn_rejects_unknown_preset(tmp_path):
    """spawn() should reject a model_preset not in the allowed list."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        spawn_presets={"fast": MagicMock()},
    )

    result = await mgr.spawn(task="do task", model_preset="unknown")
    assert "not in allowed spawn_presets" in result
    assert "unknown" in result


@pytest.mark.asyncio
async def test_spawn_without_preset_uses_default_model(tmp_path):
    """Without model_preset, spawn should use the parent's model (existing behavior)."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "default-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._announce_result = AsyncMock()

    seen = {}

    async def fake_run(spec):
        seen["model"] = spec.model
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    await mgr.spawn(task="do task")
    await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)

    assert seen["model"] == "default-model"


@pytest.mark.asyncio
async def test_spawn_presets_empty_rejects_any_preset(tmp_path):
    """When spawn_presets is empty, any model_preset should be rejected."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        spawn_presets={},
    )

    result = await mgr.spawn(task="do task", model_preset="anything")
    assert "not in allowed spawn_presets" in result


@pytest.mark.asyncio
async def test_spawn_tool_description_lists_presets(tmp_path):
    """SpawnTool.description should list available presets when configured."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.spawn import SpawnTool
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ModelPresetConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        spawn_presets={
            "fast": ModelPresetConfig(model="fast-model"),
            "smart": ModelPresetConfig(model="smart-model"),
        },
    )

    tool = SpawnTool(mgr)
    desc = tool.description
    assert "fast" in desc
    assert "smart" in desc
    assert "Available model presets" in desc


@pytest.mark.asyncio
async def test_spawn_tool_description_no_presets(tmp_path):
    """SpawnTool.description should not mention presets when none are configured."""
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.spawn import SpawnTool
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    tool = SpawnTool(mgr)
    desc = tool.description
    assert "Available model presets" not in desc


@pytest.mark.asyncio
async def test_spawn_with_preset_temperature_override(tmp_path):
    """An explicit temperature should override the preset's default temperature."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ModelPresetConfig
    from nanobot.providers.factory import ProviderSnapshot

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "default-model"

    preset_cfg = ModelPresetConfig(model="preset-model", temperature=0.5)
    preset_provider = MagicMock()
    preset_provider.generation = SimpleNamespace(
        temperature=0.5, max_tokens=8192, reasoning_effort=None,
    )
    snapshot = ProviderSnapshot(
        provider=preset_provider,
        model="preset-model",
        context_window_tokens=65536,
        signature=("test",),
    )

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        spawn_presets={"fast": preset_cfg},
        preset_snapshot_loader=lambda name: snapshot,
    )
    mgr._announce_result = AsyncMock()

    seen = {}

    async def fake_run(spec):
        seen["temperature"] = spec.temperature
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[],
        )

    with patch.object(AgentRunner, "run", AsyncMock(side_effect=fake_run)):
        await mgr.spawn(task="do task", model_preset="fast", temperature=0.9)
        await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)

    assert seen["temperature"] == 0.9


@pytest.mark.asyncio
async def test_spawn_preset_rebuilds_runner_on_signature_change(tmp_path):
    """A changed preset snapshot (config hot reload) must rebuild the runner,
    not reuse a cached AgentRunner bound to the stale provider/model."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ModelPresetConfig
    from nanobot.providers.factory import ProviderSnapshot

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "default-model"

    preset_cfg = ModelPresetConfig(model="preset-model", provider="auto")

    old_provider = MagicMock()
    old_provider.generation = SimpleNamespace(
        temperature=0.5, max_tokens=4096, reasoning_effort=None,
    )
    old_snapshot = ProviderSnapshot(
        provider=old_provider,
        model="old-model",
        context_window_tokens=32768,
        signature=("model_preset", "fast", "v1"),
    )
    new_provider = MagicMock()
    new_provider.generation = SimpleNamespace(
        temperature=0.7, max_tokens=8192, reasoning_effort=None,
    )
    new_snapshot = ProviderSnapshot(
        provider=new_provider,
        model="new-model",
        context_window_tokens=65536,
        signature=("model_preset", "fast", "v2"),
    )

    snapshots = iter([old_snapshot, new_snapshot])

    def fake_loader(name):
        assert name == "fast"
        return next(snapshots)

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        spawn_presets={"fast": preset_cfg},
        preset_snapshot_loader=fake_loader,
    )
    mgr._announce_result = AsyncMock()

    captured = []

    async def fake_run(spec):
        captured.append({
            "model": spec.model,
            "max_tokens": spec.max_tokens,
            "context_window_tokens": spec.context_window_tokens,
        })
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[],
        )

    with patch.object(AgentRunner, "run", AsyncMock(side_effect=fake_run)):
        await mgr.spawn(task="first", model_preset="fast")
        await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)
        first_runner = mgr._preset_cache["fast"][1]
        assert first_runner.provider is old_provider

        await mgr.spawn(task="second", model_preset="fast")
        await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)
        second_runner = mgr._preset_cache["fast"][1]
        assert second_runner.provider is new_provider
        assert second_runner is not first_runner

    assert len(captured) == 2
    assert captured[0]["model"] == "old-model"
    assert captured[1]["model"] == "new-model"
    assert captured[1]["max_tokens"] == 8192
    assert captured[1]["context_window_tokens"] == 65536
    assert len(mgr._preset_cache) == 1
    assert mgr._preset_cache["fast"][0] == new_snapshot.signature
