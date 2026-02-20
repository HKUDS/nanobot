"""Tests for trace capture functionality."""

import json
import shutil
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nanobot.agent.loop import AgentLoop
from nanobot.agent.trace import TraceWriter
from nanobot.config.schema import TraceConfig
from nanobot.bus.queue import MessageBus
from nanobot.agent.loop import AgentLoop
from nanobot.agent.trace import TraceWriter
from nanobot.config.schema import TraceConfig
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

class FakeProvider(LLMProvider):
    def __init__(self):
        super().__init__()
        self.responses = []

    async def chat(self, messages, **kwargs):
        if not self.responses:
            return LLMResponse(content="No more responses")
        return self.responses.pop(0)

    def get_default_model(self) -> str:
        return "test-model"

@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws

@pytest.fixture
def trace_config():
    """Create a default trace config."""
    return TraceConfig(enabled=True, dir="traces")

async def test_trace_writer_structure(workspace, trace_config):
    """Test that trace writer produces correct JSON structure."""
    writer = TraceWriter(workspace, trace_config, session_id="test-session", model="test-model")
    
    # Log iteration
    writer.log_iteration_start(1, [{"role": "user", "content": "Hello"}])
    
    # Log LLM response
    writer.log_llm_response("Hello user", [])
    
    # Close
    writer.close("final_answer", "Hello user")
    
    # Verify file existence
    trace_dir = workspace / "traces"
    assert trace_dir.exists()
    files = list(trace_dir.glob("*.json"))
    assert len(files) == 1
    
    # Verify content
    data = json.loads(files[0].read_text())
    assert data["meta"]["session_id"] == "test-session"
    assert data["meta"]["model"] == "test-model"
    assert len(data["iterations"]) == 1
    assert data["iterations"][0]["i"] == 1
    assert data["iterations"][0]["llm"]["content_preview"] == "Hello user"
    assert data["termination"]["final_answer"] == "Hello user"
    assert data["termination"]["type"] == "final_answer"

async def test_trace_redaction(workspace, trace_config):
    """Test redaction of sensitive keys."""
    writer = TraceWriter(workspace, trace_config)
    
    secret = "sk-1234567890abcdef1234567890abcdef"
    text = f"Here is my key: {secret}"
    
    redacted = writer._redact(text)
    assert secret not in redacted
    assert "[REDACTED_SECRET]" in redacted

async def test_artifact_spooling(workspace, trace_config):
    """Test that large tool outputs are spooled to artifacts."""
    trace_config.max_inline_chars = 10
    trace_config.llm_preview_chars = 10
    writer = TraceWriter(workspace, trace_config)
    
    # Log iteration
    writer.log_iteration_start(1, [])
    
    # Log large tool output
    large_output = "This is a very long string that should be spooled to a file."
    writer.log_tool_execution("read_file", {"path": "test.txt"}, large_output)
    
    # Verify artifact
    artifacts_dir = workspace / "artifacts"
    assert artifacts_dir.exists()
    files = list(artifacts_dir.glob("*.txt"))
    assert len(files) == 1
    assert files[0].read_text() == large_output
    
    # Verify trace entry
    assert len(writer.iterations) == 1
    tool_entry = writer.iterations[0]["tools"][0]
    assert "artifact_path" in tool_entry
    assert tool_entry["artifact_path"].startswith("artifacts/")
    assert tool_entry["artifact_path"].endswith(files[0].name)
    assert tool_entry["result_preview"].startswith("This ...")

@pytest.mark.asyncio
async def test_agent_loop_integration(workspace, trace_config):
    """Test that AgentLoop actually generates a trace."""
    bus = MessageBus()
    provider = FakeProvider()
    
    # Setup scripted response: 1 tool call, then final answer
    provider.responses = [
        LLMResponse(
            content="I will check the file.",
            tool_calls=[ToolCallRequest(id="1", name="list_dir", arguments={"path": "."})]
        ),
        LLMResponse(content="Done.")
    ]
    
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        trace_config=trace_config
    )
    
    # Mock tool execution to avoid real FS access
    agent.tools = Mock()
    agent.tools.get_definitions.return_value = [{"name": "list_dir", "description": "d"}]
    agent.tools.execute = AsyncMock(return_value="Mocked tool output")

    # Run loop with specific session_id
    await agent._run_agent_loop([{"role": "user", "content": "list dir"}], session_id="test-session-123")
    
    # Check trace
    trace_dir = workspace / "traces"
    assert trace_dir.exists()
    files = list(trace_dir.glob("*.json"))
    assert len(files) == 1
    
    data = json.loads(files[0].read_text())
    assert data["meta"]["session_id"] == "test-session-123"
    assert len(data["iterations"]) == 2
    assert data["iterations"][0]["tools"][0]["name"] == "list_dir"
    assert data["iterations"][0]["tools"][0]["result_preview"] == "Mocked tool output"
    assert data["termination"]["type"] == "final_answer"


@pytest.mark.asyncio
async def test_fake_provider_simple_trace(workspace, trace_config):
    """
    Another test case using FakeProvider:
    Verify that a simple interaction (model says 'Hello') is traced
    correctly without any tool usage.
    """
    # Create valid trace config
    trace_config.enabled = True
    trace_config.capture_prompt = True

    bus = MessageBus()
    provider = FakeProvider()
    
    # Simple response: no tools, just text
    provider.responses = [
        LLMResponse(content="Hello there! I am a fake model.")
    ]
    
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        trace_config=trace_config
    )
    
    # We still mock tools to be safe, though none should be called
    agent.tools = Mock()
    agent.tools.execute = AsyncMock(return_value="Should not confirm")

    # Run loop
    await agent._run_agent_loop(
        [{"role": "user", "content": "Hi"}],
        session_id="simple-fake-test"
    )
    
    # Check trace
    trace_dir = workspace / "traces"
    assert trace_dir.exists()
    
    # Filter for this specific session ID to avoid conflict with other tests if any
    files = list(trace_dir.glob("*simple-fake-test.json"))
    assert len(files) == 1
    
    data = json.loads(files[0].read_text())
    assert data["meta"]["session_id"] == "simple-fake-test"
    assert len(data["iterations"]) == 1
    # Check LLM response was captured
    assert data["termination"]["final_answer"] == "Hello there! I am a fake model."
    assert data["termination"]["type"] == "final_answer"


async def test_trace_error_fields(workspace, trace_config):
    """Test that error termination uses 'error' field instead of 'final_answer'."""
    writer = TraceWriter(workspace, trace_config, session_id="test-error")
    writer.close("error", "Something went wrong")
    
    trace_dir = workspace / "traces"
    assert trace_dir.exists()
    files = list(trace_dir.glob("*.json"))
    assert len(files) == 1
    
    data = json.loads(files[0].read_text())
    assert data["termination"]["type"] == "error"
    assert "error" in data["termination"]
    assert data["termination"]["error"] == "Something went wrong"
    assert "final_answer" not in data["termination"]
