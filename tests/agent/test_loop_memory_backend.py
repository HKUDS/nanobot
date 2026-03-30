from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryBackend, MemoryStore
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, GenerationSettings


def _make_loop(tmp_path, memory_backend=None):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (50, "test")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_backend=memory_backend,
    )


def test_agent_loop_defaults_to_memory_store_backend(tmp_path):
    loop = _make_loop(tmp_path)
    assert isinstance(loop.memory_backend, MemoryStore)


def test_agent_loop_accepts_custom_backend(tmp_path):
    class FakeBackend(MemoryBackend):
        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    backend = FakeBackend()
    loop = _make_loop(tmp_path, memory_backend=backend)
    assert loop.memory_backend is backend


def test_agent_loop_registers_backend_tools(tmp_path):
    from nanobot.agent.tools.base import Tool

    class FakeTool(Tool):
        @property
        def name(self): return "fake_tool"
        @property
        def description(self): return "fake"
        @property
        def parameters(self): return {"type": "object", "properties": {}}
        async def execute(self, **kwargs): return "ok"

    class FakeBackend(MemoryBackend):
        def get_tools(self): return [FakeTool()]
        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    loop = _make_loop(tmp_path, memory_backend=FakeBackend())
    assert loop.tools.get("fake_tool") is not None


async def test_agent_loop_calls_backend_start_before_first_message(tmp_path):
    class FakeBackend(MemoryBackend):
        started = False
        async def start(self, provider): self.started = True
        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    backend = FakeBackend()
    loop = _make_loop(tmp_path, memory_backend=backend)
    await loop.process_direct("hello", session_key="cli:test")
    assert backend.started is True


async def test_per_turn_backend_consolidate_called_after_message(tmp_path):
    class FakeBackend(MemoryBackend):
        consolidate_calls = []
        @property
        def consolidates_per_turn(self): return True
        async def start(self, provider): pass
        async def consolidate(self, messages, session_key):
            self.consolidate_calls.append(session_key)
        async def retrieve(self, query, session_key, top_k=5): return ""

    backend = FakeBackend()
    loop = _make_loop(tmp_path, memory_backend=backend)
    await loop.process_direct("hello", session_key="telegram:123")
    # Allow background task to complete
    import asyncio
    await asyncio.sleep(0)
    assert "telegram:123" in backend.consolidate_calls


# ── load_memory_backend entry-point wiring ────────────────────────────────────

def test_load_memory_backend_calls_from_nanobot_config_when_present(tmp_path):
    """load_memory_backend() must call cls.from_nanobot_config(config) when the classmethod exists."""
    from unittest.mock import MagicMock, patch
    from nanobot.agent.loop import load_memory_backend

    class BackendWithFactory(MemoryBackend):
        @classmethod
        def from_nanobot_config(cls, cfg):
            instance = cls.__new__(cls)
            instance._used_factory = True
            instance._received_config = cfg
            return instance

        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    mock_ep = MagicMock()
    mock_ep.name = "graphiti"
    mock_ep.load.return_value = BackendWithFactory

    config = MagicMock()
    config.memory.backend = "graphiti"
    config.workspace_path = tmp_path

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        backend = load_memory_backend(config)

    assert isinstance(backend, BackendWithFactory)
    assert backend._used_factory is True
    assert backend._received_config is config


def test_load_memory_backend_falls_back_to_cls_init_when_no_factory(tmp_path):
    """load_memory_backend() must fall back to cls(config) when from_nanobot_config is absent."""
    from unittest.mock import MagicMock, patch
    from nanobot.agent.loop import load_memory_backend

    class SimpleBackend(MemoryBackend):
        def __init__(self, cfg):
            self._cfg = cfg

        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    mock_ep = MagicMock()
    mock_ep.name = "simple"
    mock_ep.load.return_value = SimpleBackend

    config = MagicMock()
    config.memory.backend = "simple"
    config.workspace_path = tmp_path

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        backend = load_memory_backend(config)

    assert isinstance(backend, SimpleBackend)
    assert backend._cfg is config


def test_load_memory_backend_defaults_to_memory_store_when_backend_is_default(tmp_path):
    """load_memory_backend() must return MemoryStore when backend is 'default'."""
    from unittest.mock import MagicMock
    from nanobot.agent.loop import load_memory_backend

    config = MagicMock()
    config.memory.backend = "default"
    config.workspace_path = tmp_path

    backend = load_memory_backend(config)
    assert isinstance(backend, MemoryStore)


def test_load_memory_backend_falls_back_to_memory_store_on_unknown_backend(tmp_path):
    """load_memory_backend() must fall back to MemoryStore when entry-point not found."""
    from unittest.mock import MagicMock, patch
    from nanobot.agent.loop import load_memory_backend

    config = MagicMock()
    config.memory.backend = "nonexistent-backend"
    config.workspace_path = tmp_path

    with patch("importlib.metadata.entry_points", return_value=[]):
        backend = load_memory_backend(config)

    assert isinstance(backend, MemoryStore)
