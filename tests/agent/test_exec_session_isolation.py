from types import SimpleNamespace
from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096, temperature=0.1, reasoning_effort=None)
    return provider


def test_agent_loops_do_not_share_exec_session_managers(tmp_path):
    loop_a = AgentLoop(
        bus=MessageBus(),
        provider=_provider(),
        workspace=tmp_path / "a",
        model="test-model",
        context_window_tokens=4096,
    )
    loop_b = AgentLoop(
        bus=MessageBus(),
        provider=_provider(),
        workspace=tmp_path / "b",
        model="test-model",
        context_window_tokens=4096,
    )

    exec_a = loop_a.tools.get("exec")
    stdin_a = loop_a.tools.get("write_stdin")
    list_a = loop_a.tools.get("list_exec_sessions")
    exec_b = loop_b.tools.get("exec")

    assert exec_a._session_manager is loop_a._exec_session_manager
    assert stdin_a._manager is loop_a._exec_session_manager
    assert list_a._manager is loop_a._exec_session_manager
    assert exec_b._session_manager is loop_b._exec_session_manager
    assert loop_a._exec_session_manager is not loop_b._exec_session_manager
