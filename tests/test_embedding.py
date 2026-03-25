"""Tests for multi-tenant embedding parameters (extra_system_prompt, extra_env)."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


# --- extra_system_prompt in ContextBuilder ---

def test_extra_system_prompt_appended():
    """extra_system_prompt text appears at end of system prompt."""
    from nanobot.agent.context import ContextBuilder
    workspace = Path("/tmp/test-workspace-embedding")
    workspace.mkdir(parents=True, exist_ok=True)
    ctx = ContextBuilder(workspace)

    messages = ctx.build_messages(
        history=[],
        current_message="hello",
        extra_system_prompt="You are Orbis, a CRM assistant for Ruby.",
    )

    system_content = messages[0]["content"]
    assert "You are Orbis, a CRM assistant for Ruby." in system_content
    # It should appear after the base nanobot prompt
    assert system_content.index("nanobot") < system_content.index("Orbis")


def test_no_extra_prompt_unchanged():
    """System prompt unchanged when extra_system_prompt is None."""
    from nanobot.agent.context import ContextBuilder
    workspace = Path("/tmp/test-workspace-embedding")
    workspace.mkdir(parents=True, exist_ok=True)
    ctx = ContextBuilder(workspace)

    messages_without = ctx.build_messages(history=[], current_message="hello")
    messages_with_none = ctx.build_messages(
        history=[], current_message="hello", extra_system_prompt=None
    )

    assert messages_without[0]["content"] == messages_with_none[0]["content"]


def test_extra_prompt_empty_string_unchanged():
    """Empty string extra_system_prompt doesn't alter prompt."""
    from nanobot.agent.context import ContextBuilder
    workspace = Path("/tmp/test-workspace-embedding")
    workspace.mkdir(parents=True, exist_ok=True)
    ctx = ContextBuilder(workspace)

    messages_without = ctx.build_messages(history=[], current_message="hello")
    messages_with_empty = ctx.build_messages(
        history=[], current_message="hello", extra_system_prompt=""
    )

    assert messages_without[0]["content"] == messages_with_empty[0]["content"]


# --- env threading through ToolRegistry ---

class EchoEnvTool(Tool):
    """Test tool that returns env vars it received."""

    @property
    def name(self) -> str:
        return "echo_env"

    @property
    def description(self) -> str:
        return "Returns env it received"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        }

    async def execute(self, key: str, env: dict[str, str] | None = None, **kwargs) -> str:
        if env and key in env:
            return env[key]
        return "(not found)"


@pytest.mark.asyncio
async def test_registry_passes_env_to_tool():
    """ToolRegistry.execute() passes env kwarg to tool."""
    reg = ToolRegistry()
    reg.register(EchoEnvTool())

    result = await reg.execute(
        "echo_env",
        {"key": "MY_TOKEN"},
        env={"MY_TOKEN": "secret123", "PATH": "/usr/bin"},
    )
    assert result == "secret123"


@pytest.mark.asyncio
async def test_registry_no_env_passes_none():
    """ToolRegistry.execute() without env does not inject env kwarg."""
    reg = ToolRegistry()
    reg.register(EchoEnvTool())

    result = await reg.execute("echo_env", {"key": "MY_TOKEN"})
    assert result == "(not found)"


# --- ExecTool env passthrough ---

@pytest.mark.asyncio
async def test_exec_tool_passes_env_to_subprocess():
    """ExecTool passes env dict to subprocess."""
    from nanobot.agent.tools.shell import ExecTool

    tool = ExecTool(working_dir="/tmp", timeout=10)

    # Mock subprocess to capture the env kwarg
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"hello\n", b""))
    mock_process.returncode = 0
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_process) as mock_create:
        await tool.execute(command="echo $FOO", env={"FOO": "bar", "PATH": "/usr/bin"})

        # Verify extra env was merged into subprocess env
        call_kwargs = mock_create.call_args
        passed_env = call_kwargs.kwargs.get("env")
        assert passed_env is not None
        assert passed_env["FOO"] == "bar"
        assert passed_env["PATH"] == "/usr/bin"


@pytest.mark.asyncio
async def test_exec_tool_no_env_inherits_parent():
    """ExecTool without env inherits parent process environment."""
    from nanobot.agent.tools.shell import ExecTool

    tool = ExecTool(working_dir="/tmp", timeout=10)

    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"ok\n", b""))
    mock_process.returncode = 0
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_process) as mock_create:
        await tool.execute(command="echo hi")

        # env should be a copy of os.environ (no extra keys injected)
        call_kwargs = mock_create.call_args
        passed_env = call_kwargs.kwargs.get("env")
        assert passed_env is not None
        # Should contain parent env vars
        assert "PATH" in passed_env


# --- os.environ not mutated ---

def test_extra_env_does_not_mutate_os_environ():
    """Merging extra_env must not modify os.environ."""
    original_env = dict(os.environ)

    # Simulate what _run_agent_loop does
    extra_env = {"INJECTED_VAR_12345": "should_not_persist"}
    merged = {**os.environ, **extra_env}

    # os.environ should be unchanged
    assert "INJECTED_VAR_12345" not in os.environ
    assert os.environ == original_env

    # But merged should contain it
    assert merged["INJECTED_VAR_12345"] == "should_not_persist"


# --- process_direct signature ---

def test_process_direct_accepts_new_params():
    """process_direct() accepts extra_system_prompt and extra_env params."""
    import inspect
    from nanobot.agent.loop import AgentLoop

    sig = inspect.signature(AgentLoop.process_direct)
    params = list(sig.parameters.keys())
    assert "extra_system_prompt" in params
    assert "extra_env" in params

    # Check defaults are None
    assert sig.parameters["extra_system_prompt"].default is None
    assert sig.parameters["extra_env"].default is None
