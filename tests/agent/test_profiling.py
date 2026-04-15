import pytest
from nanobot.agent.profiling import ProfilingHook, is_profiling_enabled
from nanobot.agent.hook import AgentHookContext

def test_profiling_disabled_by_default():
    assert not is_profiling_enabled({})

def test_profiling_enabled_via_config():
    assert is_profiling_enabled({"profiling": True})

def test_profiling_enabled_via_env(monkeypatch):
    monkeypatch.setenv("NANOBOT_PROFILING", "1")
    assert is_profiling_enabled({})

@pytest.mark.asyncio
async def test_hook_records_iteration_timing():
    hook = ProfilingHook()
    ctx = AgentHookContext(iteration=0, messages=[])
    await hook.before_iteration(ctx)
    await hook.after_iteration(ctx)
    assert hook.last_iteration_ms >= 0
    assert hook.total_iterations == 1

@pytest.mark.asyncio
async def test_hook_records_tool_timing():
    hook = ProfilingHook()
    ctx = AgentHookContext(iteration=0, messages=[])
    await hook.before_iteration(ctx)
    await hook.before_execute_tools(ctx)
    await hook.after_iteration(ctx)
    assert hook.last_tool_batch_ms >= 0

@pytest.mark.asyncio
async def test_hook_resets_tool_timing_when_no_tools():
    hook = ProfilingHook()
    ctx = AgentHookContext(iteration=0, messages=[])
    await hook.before_iteration(ctx)
    await hook.after_iteration(ctx)
    assert hook.last_tool_batch_ms == 0.0
