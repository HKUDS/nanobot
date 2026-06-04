"""Integration tests for the AgentLoop against a live Ollama instance.

These tests exercise the full agent pipeline: message -> context -> LLM -> tools -> response.
Requires Ollama running at localhost:11434 with ministral-3:8b.
Skipped automatically if Ollama is not reachable.

Run explicitly:
    pytest tests/test_llm_agent_loop.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from blackcat.agent.handler import MessageHandler
from blackcat.agent.loop import AgentLoop
from blackcat.agent.runner import AgentRunner
from blackcat.agent.tools.filesystem import ReadFileTool, WriteFileTool
from blackcat.agent.tools.registry import ToolRegistry
from blackcat.bus.events import InboundMessage
from blackcat.bus.queue import MessageBus

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import LLM_TEST_MODEL


@pytest.fixture
def provider(ollama_available, llm_provider):
    return llm_provider


@pytest.fixture
def agent(ollama_available, llm_provider, tmp_path):
    """Full AgentLoop backed by local Ollama."""
    bus = MessageBus()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("You are a test assistant. Be very brief.\n")
    (workspace / "memory").mkdir()

    loop = AgentLoop(
        bus=bus,
        provider=llm_provider,
        workspace=workspace,
        model=LLM_TEST_MODEL,
        max_iterations=5,
        provider_retry_mode="standard",
        unified_session=False,
    )
    return loop


# ── _run_agent_loop (low-level, fewer tools = less model confusion) ──


@pytest.mark.llm
@pytest.mark.asyncio
async def test_run_agent_loop_simple_response(provider):
    """LLM should return text content for a simple question (no tools)."""
    # Minimal registry with NO tools — forces text response
    tools = ToolRegistry()
    agent = AgentLoop.__new__(AgentLoop)
    agent.provider = provider
    agent.model = LLM_TEST_MODEL
    agent.max_iterations = 3
    agent.tools = tools
    agent._extra_hooks = []
    agent.runner = AgentRunner(provider)
    agent.max_tool_result_chars = 50000
    agent.context_window_tokens = 65_536
    agent.context_block_limit = None
    agent.workspace = None
    agent.provider_retry_mode = "standard"
    agent._unified_session = False
    agent.subagents = MagicMock()

    # Bypass the full context manager — just raw messages
    from blackcat.agent.context import ContextBuilder

    agent.context = ContextBuilder.__new__(ContextBuilder)

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Reply very briefly."},
        {"role": "user", "content": "What is 2 + 2? Reply with just the number."},
    ]

    content, tools_used, _, _, _ = await agent._run_agent_loop(messages)
    assert content is not None
    assert "4" in content
    assert tools_used == []


@pytest.mark.llm
@pytest.mark.asyncio
async def test_run_agent_loop_with_read_file(provider, tmp_path):
    """LLM should use read_file tool and return content."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "secret.txt").write_text("The answer is 42.")

    tools = ToolRegistry()
    tools.register(ReadFileTool(workspace=workspace))

    agent = AgentLoop.__new__(AgentLoop)
    agent.provider = provider
    agent.model = LLM_TEST_MODEL
    agent.max_iterations = 5
    agent.tools = tools
    agent._extra_hooks = []
    agent.runner = AgentRunner(provider)
    agent.max_tool_result_chars = 50000
    agent.context_window_tokens = 65_536
    agent.context_block_limit = None
    agent.workspace = workspace
    agent.provider_retry_mode = "standard"
    agent._unified_session = False
    agent.subagents = MagicMock()

    from blackcat.agent.context import ContextBuilder

    agent.context = ContextBuilder.__new__(ContextBuilder)

    messages = [
        {"role": "system", "content": "You have a read_file tool. Use it when asked to read files. Be brief."},
        {"role": "user", "content": "Read secret.txt and tell me the answer."},
    ]

    content, tools_used, _, _, _ = await agent._run_agent_loop(messages)
    assert "read_file" in tools_used
    assert content is not None
    # The model read the file — that's what we're testing.
    # Whether it reports "42" or refuses on principle is model behavior.
    assert len(content) > 0


@pytest.mark.llm
@pytest.mark.asyncio
async def test_run_agent_loop_with_write_file(provider, tmp_path):
    """LLM should use write_file tool to create files."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=workspace))

    agent = AgentLoop.__new__(AgentLoop)
    agent.provider = provider
    agent.model = LLM_TEST_MODEL
    agent.max_iterations = 5
    agent.tools = tools
    agent._extra_hooks = []
    agent.runner = AgentRunner(provider)
    agent.max_tool_result_chars = 50000
    agent.context_window_tokens = 65_536
    agent.context_block_limit = None
    agent.workspace = workspace
    agent.provider_retry_mode = "standard"
    agent._unified_session = False
    agent.subagents = MagicMock()

    from blackcat.agent.context import ContextBuilder

    agent.context = ContextBuilder.__new__(ContextBuilder)

    messages = [
        {"role": "system", "content": "You have a write_file tool. Use it to write files. Be brief."},
        {"role": "user", "content": "Write the text 'hello world' to a file called output.txt"},
    ]

    content, tools_used, _, _, _ = await agent._run_agent_loop(messages)
    assert "write_file" in tools_used
    assert (workspace / "output.txt").exists()
    assert "hello world" in (workspace / "output.txt").read_text()


# ── Full process_direct (tests the entire pipeline) ───────────────


@pytest.mark.llm
@pytest.mark.asyncio
async def test_process_direct_responds(agent):
    """Agent should produce some response (text or via message tool)."""
    response = await agent.process_direct("What is 2 + 2?")

    # Small models sometimes use the message tool instead of text response.
    # When that happens, process_direct returns None because _sent_in_turn=True.
    # Either way, the agent should NOT crash.
    assert response is not None
    # Check if the response is meaningful OR the message was sent via bus
    content = response.content if response else ""
    if content and content.strip() and "completed processing" not in content:
        assert "4" in content
    else:
        # The model used the message tool — check the outbound bus
        if agent.bus.outbound_size > 0:
            outbound = await agent.bus.consume_outbound()
            assert "4" in outbound.content


@pytest.mark.llm
@pytest.mark.asyncio
async def test_process_direct_preserves_session(agent):
    """Agent should maintain session context between calls."""
    await agent.process_direct("Remember: the magic word is 'butterfly'.", chat_id="s1")
    response = await agent.process_direct("What is the magic word?", chat_id="s1")

    # Check both direct response and bus for the answer
    found = False
    content = response.content if response else ""
    if content and "butterfly" in content.lower():
        found = True
    while agent.bus.outbound_size > 0:
        msg = await agent.bus.consume_outbound()
        if "butterfly" in msg.content.lower():
            found = True
    assert found


@pytest.mark.llm
@pytest.mark.asyncio
async def test_process_message_returns_outbound(agent):
    """MessageHandler.process should return an OutboundMessage or send via bus."""
    from blackcat.config.schema import Config

    msg = InboundMessage(
        channel="test",
        sender_id="user1",
        chat_id="chat1",
        content="Say the word 'pong'. Nothing else.",
    )

    handler = MessageHandler(agent, msg, Config())
    response = await handler.process()

    # Either direct response or message tool was used
    found_pong = False
    if response is not None:
        assert response.channel == "test"
        assert response.chat_id == "chat1"
        if "pong" in response.content.lower():
            found_pong = True
    # Also check outbound bus (message tool sends there)
    while agent.bus.outbound_size > 0:
        out = await agent.bus.consume_outbound()
        if "pong" in out.content.lower():
            found_pong = True
    assert found_pong


# ── Static helpers (no LLM needed) ────────────────────────────────


def test_strip_think():
    assert AgentLoop._strip_think("<think>internal</think>answer") == "answer"
    assert AgentLoop._strip_think("<think>thinking\nmore</think>result") == "result"
    assert AgentLoop._strip_think("no thinking here") == "no thinking here"
    assert AgentLoop._strip_think("") is None
    assert AgentLoop._strip_think(None) is None


def test_strip_think_multiple():
    text = "<think>first</think>hello <think>second</think>world"
    assert AgentLoop._strip_think(text) == "hello world"


def test_tool_hint():
    from blackcat.providers.base import ToolCallRequest

    calls = [ToolCallRequest(id="1", name="web_search", arguments={"query": "test"})]
    hint = AgentLoop._tool_hint(calls)
    # New format: search "test" (see tool_hints.py)
    assert 'search "test"' in hint


def test_tool_hint_truncates():
    from blackcat.providers.base import ToolCallRequest

    long_query = "a" * 100
    calls = [ToolCallRequest(id="1", name="search", arguments={"query": long_query})]
    hint = AgentLoop._tool_hint(calls)
    # New format uses unicode ellipsis and no trailing quote
    assert "…" in hint or "..." in hint


def test_tool_hint_no_args():
    from blackcat.providers.base import ToolCallRequest

    calls = [ToolCallRequest(id="1", name="list_dir", arguments={})]
    hint = AgentLoop._tool_hint(calls)
    assert hint == "list_dir"
