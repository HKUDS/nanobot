import pytest
from unittest.mock import MagicMock


def _make_loop(tmp_path, session_backend="normal", memory_backend="normal",
               session_manager=None, memory_store=None):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = MagicMock()
    provider.generation.max_tokens = 4096

    bus = MessageBus()
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        session_backend=session_backend,
        memory_backend=memory_backend,
        session_manager=session_manager,
        memory_store=memory_store,
    )


def test_loop_default_backends_load(tmp_path):
    from nanobot.session.manager import NormalSessionManager
    from nanobot.memory.store import NormalMemoryStore

    loop = _make_loop(tmp_path)
    assert isinstance(loop.sessions, NormalSessionManager)
    assert isinstance(loop.memory_consolidator.store, NormalMemoryStore)


def test_loop_unknown_session_backend_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown session backend"):
        _make_loop(tmp_path, session_backend="nonexistent")


def test_loop_unknown_memory_backend_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown memory backend"):
        _make_loop(tmp_path, memory_backend="nonexistent")


def test_loop_injected_session_manager_takes_priority(tmp_path):
    from nanobot.session.manager import NormalSessionManager
    custom_mgr = NormalSessionManager(tmp_path)
    loop = _make_loop(tmp_path, session_manager=custom_mgr)
    assert loop.sessions is custom_mgr


def test_loop_injected_memory_store_takes_priority(tmp_path):
    from nanobot.memory.store import NormalMemoryStore
    custom_store = NormalMemoryStore(tmp_path)
    loop = _make_loop(tmp_path, memory_store=custom_store)
    assert loop.memory_consolidator.store is custom_store
