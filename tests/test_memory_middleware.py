from typing import Any

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryMiddleware, MemoryStore
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session


class DummyProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


class DummySessions:
    def __init__(self) -> None:
        self.session = Session(key="cli:direct")
        self.saved = False

    def get_or_create(self, key: str) -> Session:
        self.session.key = key
        return self.session

    def save(self, session: Session) -> None:
        self.saved = True


class MockMemoryMiddleware:
    """Mock middleware for testing lifecycle and method calls."""
    
    def __init__(self) -> None:
        self.initialized = False
        self.cleaned_up = False
        self.retrieve_calls: list[tuple[str, list | None, dict]] = []
        self.write_calls: list[tuple[str, str, dict]] = []
        self.retrieve_return = ""
    
    async def initialize(self) -> None:
        self.initialized = True
    
    async def retrieve(
        self,
        user_input: str,
        history: list[dict[str, Any]] | None,
        metadata: dict[str, Any],
    ) -> str:
        self.retrieve_calls.append((user_input, history, metadata))
        return self.retrieve_return
    
    async def write(
        self,
        user_input: str,
        llm_output: str,
        metadata: dict[str, Any],
    ) -> None:
        self.write_calls.append((user_input, llm_output, metadata))
    
    async def cleanup(self) -> None:
        self.cleaned_up = True



# =============================================================================
# ContextBuilder Tests
# =============================================================================


def test_context_builder_static_memory_in_system_prompt(tmp_path) -> None:
    """Verify static MEMORY.md content is included in system prompt."""
    from nanobot.agent.memory import MemoryStore
    
    store = MemoryStore(tmp_path)
    store.write_long_term("static long-term memory content")
    
    ctx = ContextBuilder(tmp_path)
    messages = ctx.build_messages(
        history=[],
        current_message="hi",
    )

    # Static memory should be in the system prompt
    system_prompt = messages[0]["content"]
    assert "# Memory" in system_prompt
    assert "static long-term memory content" in system_prompt


def test_context_builder_ephemeral_retrieved_context(tmp_path) -> None:
    """Verify retrieved context appears as synthetic assistant message before user."""
    ctx = ContextBuilder(tmp_path)
    messages = ctx.build_messages(
        history=[{"role": "assistant", "content": "prev"}],
        current_message="hi",
        retrieved_context="retrieved memory content",
    )

    # Should have: system, history assistant, synthetic assistant, user
    assert len(messages) == 4
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "prev"
    
    # Synthetic assistant message with retrieved context
    assert messages[2]["role"] == "assistant"
    assert "[Retrieved Context]" in messages[2]["content"]
    assert "retrieved memory content" in messages[2]["content"]
    
    # User message is last
    assert messages[3]["role"] == "user"
    assert messages[3]["content"] == "hi"


def test_context_builder_no_synthetic_message_without_context(tmp_path) -> None:
    """Verify no synthetic message is injected when retrieved_context is None."""
    ctx = ContextBuilder(tmp_path)
    messages = ctx.build_messages(
        history=[{"role": "assistant", "content": "prev"}],
        current_message="hi",
        retrieved_context=None,
    )

    # Should have: system, history assistant, user (no synthetic)
    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "prev"
    assert messages[2]["role"] == "user"


# =============================================================================
# AgentLoop Integration Tests
# =============================================================================


async def test_agent_calls_middleware_methods(tmp_path) -> None:
    mock = MockMemoryMiddleware()
    mock.retrieve_return = "retrieved memory"

    bus = MessageBus()
    agent = AgentLoop(
        bus=bus,
        provider=DummyProvider(),
        workspace=tmp_path,
        model="dummy",
        memory=mock,
    )
    agent.sessions = DummySessions()
    
    # Simulate initialize (normally done in run())
    await agent.memory.initialize()
    assert mock.initialized

    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="hello",
    )

    response = await agent._process_message(msg)
    assert response is not None
    assert response.content == "ok"

    # Verify retrieve was called
    assert len(mock.retrieve_calls) == 1
    assert mock.retrieve_calls[0][0] == "hello"
    assert mock.retrieve_calls[0][1] == []

    # Verify write was called
    assert len(mock.write_calls) == 1
    assert mock.write_calls[0][0] == "hello"
    assert mock.write_calls[0][1] == "ok"
    write_metadata = mock.write_calls[0][2]
    assert write_metadata["session_key"] == "cli:direct"
    assert write_metadata["channel"] == "cli"
    assert write_metadata["chat_id"] == "direct"


async def test_agent_stop_calls_cleanup(tmp_path) -> None:
    mock = MockMemoryMiddleware()
    
    bus = MessageBus()
    agent = AgentLoop(
        bus=bus,
        provider=DummyProvider(),
        workspace=tmp_path,
        model="dummy",
        memory=mock,
    )
    
    # Simulate running
    agent._memory_initialized = True
    
    await agent.stop()
    assert mock.cleaned_up


async def test_middleware_conforms_to_protocol() -> None:
    """Verify implementations satisfy MemoryMiddleware protocol."""
    # Runtime check using isinstance with Protocol
    mock = MockMemoryMiddleware()
    assert isinstance(mock, MemoryMiddleware)
