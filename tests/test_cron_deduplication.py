
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse

class MockProvider(LLMProvider):
    def __init__(self):
        super().__init__()
        self.last_tools = []
        self.responses = []

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.last_tools = tools or []
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Mock response")

    def get_default_model(self):
        return "mock-model"

@pytest.mark.asyncio
async def test_agent_loop_tool_exclusion(tmp_path):
    """Test that AgentLoop correctly excludes tools when requested."""
    bus = MessageBus()
    provider = MockProvider()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Create required bootstrap files to avoid errors
    (workspace / "AGENTS.md").write_text("Instruction")
    (workspace / "memory").mkdir()
    
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="mock-model"
    )
    
    # Test 1: Normal execution (no exclusion)
    provider.responses = [LLMResponse(content="Normal")]
    await agent.process_direct("Hello")
    
    tool_names_normal = [t["function"]["name"] for t in provider.last_tools]
    assert "message" in tool_names_normal, "Message tool should be present by default"
    
    # Test 2: Execution with exclusion
    provider.responses = [LLMResponse(content="Excluded")]
    await agent.process_direct("Hello", excluded_tools=["message"])
    
    tool_names_excluded = [t["function"]["name"] for t in provider.last_tools]
    assert "message" not in tool_names_excluded, "Message tool should be excluded"
    assert "read_file" in tool_names_excluded, "Other tools should remain"

@pytest.mark.asyncio
async def test_cron_execution_logic(tmp_path):
    """Test that execute_cron_job calls agent with exclusion."""
    from nanobot.cli.commands import execute_cron_job
    from nanobot.cron.types import CronJob, CronPayload, CronSchedule, CronJobState
    
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    
    agent = MagicMock()
    agent.process_direct = AsyncMock(return_value="Task Result")
    
    job = CronJob(
        id="123",
        name="test",
        enabled=True,
        schedule=CronSchedule(kind="every", every_ms=1000),
        payload=CronPayload(
            kind="agent_turn",
            message="Do task",
            deliver=True,
            channel="telegram",
            to="user1"
        ),
        state=CronJobState()
    )
    
    # Execute
    await execute_cron_job(job, bus, agent)
    
    # Verify agent was called with excluded_tools=["message"]
    args, kwargs = agent.process_direct.call_args
    assert kwargs.get("excluded_tools") == ["message"], "Agent should be called with excluded_tools=['message']"
    
    # Verify instruction is simple
    instruction = args[0]
    assert "Return the result as text" in instruction
    assert "Return ONLY" not in instruction # Old instruction check
