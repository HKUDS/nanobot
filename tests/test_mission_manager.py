"""Tests for the background mission manager."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nanobot.config.schema import AgentRoleConfig
from nanobot.config.sub_agent import SubAgentConfig
from nanobot.coordination.mission import Mission, MissionManager, MissionStatus
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.builtin.mission import (
    MissionCancelTool,
    MissionListTool,
    MissionStartTool,
    MissionStatusTool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyProvider:
    """Scripted LLM provider for deterministic test scenarios."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    async def chat(self, **_kwargs: object) -> LLMResponse:
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "openai/gpt-4.1"


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo back text"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult.ok(str(kwargs.get("text", "")))


def _make_bus() -> SimpleNamespace:
    return SimpleNamespace(publish_outbound=AsyncMock())


def _default_delegation_tools(workspace: Path | None = None) -> dict:
    from nanobot.tools.setup import build_delegation_tools

    return build_delegation_tools(workspace=workspace or Path("/tmp/test-workspace"))


def _make_manager(
    responses: list[LLMResponse] | None = None,
    bus: SimpleNamespace | None = None,
) -> MissionManager:
    responses = responses or [LLMResponse(content="Mission result.")]
    return MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_DummyProvider(responses),
        bus=bus or _make_bus(),
        max_iterations=3,
        delegation_tools=_default_delegation_tools(),
    )


# ---------------------------------------------------------------------------
# Mission lifecycle
# ---------------------------------------------------------------------------


async def test_start_returns_pending_mission() -> None:
    """start() should return a Mission immediately with PENDING status."""
    mgr = _make_manager()
    # Patch _execute_mission to avoid actual LLM call
    mgr._execute_mission = AsyncMock()  # type: ignore[method-assign]
    mission = await mgr.start("analyse code", label="code-audit")
    assert isinstance(mission, Mission)
    assert mission.label == "code-audit"
    assert mission.role == "pending"
    assert len(mission.id) == 8


async def test_mission_completes_with_result() -> None:
    """A mission should run to completion and deliver via OutboundMessage."""
    bus = _make_bus()
    provider = _DummyProvider([LLMResponse(content="## Findings\nAll good.")])
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=provider,
        bus=bus,
        max_iterations=2,
        delegation_tools=_default_delegation_tools(),
    )
    mission = await mgr.start("check health")
    # Await the background task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        _ = await task

    assert mission.status == MissionStatus.COMPLETED
    assert mission.result is not None
    assert "Findings" in mission.result
    bus.publish_outbound.assert_awaited()


async def test_mission_delivers_on_failure() -> None:
    """If the LLM raises, the mission should FAIL and still deliver a message."""

    class _FailProvider:
        async def chat(self, **_kwargs: object) -> LLMResponse:
            raise RuntimeError("provider unavailable")

        def get_default_model(self) -> str:
            return "openai/gpt-4.1"

    bus = _make_bus()
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_FailProvider(),  # type: ignore[arg-type]
        bus=bus,
        max_iterations=2,
        delegation_tools=_default_delegation_tools(),
    )

    mission = await mgr.start("some task")
    # Await the background task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        _ = await task

    assert mission.status == MissionStatus.FAILED
    assert "failed" in (mission.result or "").lower()
    bus.publish_outbound.assert_awaited()


async def test_mission_grounded_when_tools_used() -> None:
    """Grounded flag should be True when the agent used at least one tool."""
    responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="tc1", name="echo", arguments={"text": "hi"})],
        ),
        LLMResponse(content="## Findings\nEcho worked."),
    ]
    bus = _make_bus()
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_DummyProvider(responses),
        bus=bus,
        max_iterations=3,
        delegation_tools=_default_delegation_tools(),
    )

    mission = await mgr.start("echo test")
    # Await the background task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        _ = await task

    assert mission.grounded is True
    assert "echo" in mission.tools_used


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------


async def test_resolve_role_falls_back_to_general() -> None:
    """Without a coordinator, _resolve_role should return 'general'."""
    mgr = _make_manager()
    role = await mgr._resolve_role("anything")
    assert role.name == "general"


async def test_resolve_role_uses_coordinator_when_available() -> None:
    """When a coordinator is set, _resolve_role should call it."""
    mgr = _make_manager()
    code_role = AgentRoleConfig(name="code", description="Code specialist")
    mgr.coordinator = SimpleNamespace(route=AsyncMock(return_value=code_role))  # type: ignore[assignment]
    role = await mgr._resolve_role("fix a bug")
    assert role.name == "code"


# ---------------------------------------------------------------------------
# MissionStartTool
# ---------------------------------------------------------------------------


async def test_mission_start_tool_returns_confirmation() -> None:
    """MissionStartTool.execute() should return a success ToolResult."""
    mgr = _make_manager()
    mgr._execute_mission = AsyncMock()  # type: ignore[method-assign]
    tool = MissionStartTool(manager=mgr)
    tool.set_context("telegram", "chat123")

    result = await tool.execute(task="audit the codebase", label="audit")
    assert result.success is True
    assert "started" in result.output.lower()


def test_mission_start_tool_name_and_desc() -> None:
    """Verify tool metadata."""
    mgr = _make_manager()
    tool = MissionStartTool(manager=mgr)
    assert tool.name == "mission_start"
    assert "background" in tool.description.lower()
    assert "task" in tool.parameters["properties"]


# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------


def test_list_active_and_get() -> None:
    """list_active and get should track missions correctly."""
    mgr = _make_manager()
    m = Mission(
        id="abc123",
        task="t",
        label="l",
        role="general",
        status=MissionStatus.RUNNING,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    mgr._missions["abc123"] = m
    assert mgr.get("abc123") is m
    assert mgr.list_active() == [m]

    m.status = MissionStatus.COMPLETED
    assert mgr.list_active() == []


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def test_cancel_sets_cancelled_status() -> None:
    """Cancelling a running mission should set CANCELLED and deliver notification."""

    class _SlowProvider:
        async def chat(self, **_kwargs: object) -> LLMResponse:
            await asyncio.sleep(10)  # Will be cancelled before this completes
            return LLMResponse(content="never")

        def get_default_model(self) -> str:
            return "openai/gpt-4.1"

    bus = _make_bus()
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_SlowProvider(),  # type: ignore[arg-type]
        bus=bus,
        max_iterations=3,
        delegation_tools=_default_delegation_tools(),
    )

    mission = await mgr.start("long task")
    # Yield to event loop so background task starts and sets status to RUNNING
    await asyncio.sleep(0)
    assert mission.status == MissionStatus.RUNNING

    result = mgr.cancel(mission.id)
    assert result is True

    # Wait for cancellation to propagate by awaiting the task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        try:
            _ = await task
        except asyncio.CancelledError:
            pass  # Expected when mission is cancelled; safe to ignore

    assert mission.status == MissionStatus.CANCELLED
    assert mission.result == "Mission cancelled by user."
    bus.publish_outbound.assert_awaited()


def test_cancel_nonexistent_returns_false() -> None:
    """Cancelling an unknown mission ID returns False."""
    mgr = _make_manager()
    assert mgr.cancel("nonexistent") is False


def test_cancel_completed_returns_false() -> None:
    """Cancelling an already-completed mission returns False."""
    mgr = _make_manager()
    m = Mission(
        id="done1",
        task="t",
        label="l",
        role="general",
        status=MissionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
    )
    mgr._missions["done1"] = m
    assert mgr.cancel("done1") is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


async def test_concurrent_missions_complete_independently() -> None:
    """Multiple missions launched simultaneously should all complete."""
    responses = [LLMResponse(content=f"Result {i}") for i in range(3)]
    bus = _make_bus()
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_DummyProvider(responses),
        bus=bus,
        max_iterations=2,
        delegation_tools=_default_delegation_tools(),
    )

    missions = [await mgr.start(f"task {i}", label=f"t{i}") for i in range(3)]
    # Await all background tasks directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        _ = await task

    for m in missions:
        assert m.status == MissionStatus.COMPLETED
    assert bus.publish_outbound.await_count == 3


async def test_result_truncation_in_delivery() -> None:
    """OutboundMessage body should be truncated when result is very long."""
    long_content = "x" * 10000
    bus = _make_bus()
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_DummyProvider([LLMResponse(content=long_content)]),
        bus=bus,
        max_iterations=2,
        delegation_tools=_default_delegation_tools(),
    )

    mission = await mgr.start("long task")
    # Await the background task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        _ = await task

    assert mission.status == MissionStatus.COMPLETED
    # Full result stored on mission
    assert len(mission.result or "") == 10000

    # Delivered message truncated
    call_args = bus.publish_outbound.call_args[0][0]
    assert len(call_args.content) <= 4000
    assert "truncated" in call_args.content


async def test_bus_delivery_failure_does_not_crash() -> None:
    """If bus.publish_outbound raises, mission should still be COMPLETED."""
    bus = _make_bus()
    bus.publish_outbound = AsyncMock(side_effect=RuntimeError("bus down"))
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_DummyProvider([LLMResponse(content="ok")]),
        bus=bus,
        max_iterations=2,
        delegation_tools=_default_delegation_tools(),
    )

    mission = await mgr.start("test")
    # Await the background task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        _ = await task

    assert mission.status == MissionStatus.COMPLETED
    assert mission.result == "ok"


async def test_retry_when_no_tools_used() -> None:
    """Agent that uses no tools on first pass should retry and use tools on second."""
    responses = [
        # First pass: no tools, just text
        LLMResponse(content="I will search."),
        # Retry pass: uses echo tool
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="tc1", name="echo", arguments={"text": "found"})],
        ),
        LLMResponse(content="## Findings\nFound via retry."),
    ]
    bus = _make_bus()
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_DummyProvider(responses),
        bus=bus,
        max_iterations=5,
        delegation_tools=_default_delegation_tools(),
    )

    mission = await mgr.start("investigate something")
    # Await the background task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        _ = await task

    assert mission.grounded is True
    assert "echo" in mission.tools_used
    assert "retry" in (mission.result or "").lower()


def test_role_denied_tools_filtered() -> None:
    """_build_tool_registry should remove denied tools."""
    mgr = _make_manager()
    role = AgentRoleConfig(name="safe", description="Safe role", denied_tools=["exec"])
    tools = mgr._build_tool_registry(role)
    assert "exec" not in tools._tools
    assert "read_file" in tools._tools


def test_role_allowed_tools_whitelist() -> None:
    """_build_tool_registry should keep only allowed tools when set."""
    mgr = _make_manager()
    role = AgentRoleConfig(
        name="minimal",
        description="Minimal",
        allowed_tools=["read_file", "list_dir"],
    )
    tools = mgr._build_tool_registry(role)
    assert set(tools._tools.keys()) == {"read_file", "list_dir"}


# ---------------------------------------------------------------------------
# MissionStatusTool
# ---------------------------------------------------------------------------


async def test_mission_status_tool_returns_info() -> None:
    """mission_status should return JSON with mission details."""
    mgr = _make_manager()
    m = Mission(
        id="stat01",
        task="audit",
        label="audit",
        role="code",
        status=MissionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        result="All good.",
        tools_used=["read_file"],
        grounded=True,
    )
    mgr._missions["stat01"] = m

    tool = MissionStatusTool(manager=mgr)
    result = await tool.execute(mission_id="stat01")
    assert result.success is True
    assert '"status": "completed"' in result.output
    assert '"grounded": true' in result.output


async def test_mission_status_tool_not_found() -> None:
    """mission_status should fail for unknown mission ID."""
    mgr = _make_manager()
    tool = MissionStatusTool(manager=mgr)
    result = await tool.execute(mission_id="nope")
    assert result.success is False
    assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# MissionListTool
# ---------------------------------------------------------------------------


async def test_mission_list_tool_returns_all() -> None:
    """mission_list should list missions with mixed statuses."""
    mgr = _make_manager()
    now = datetime.now(timezone.utc)
    for i, status in enumerate(
        [MissionStatus.COMPLETED, MissionStatus.RUNNING, MissionStatus.FAILED]
    ):
        mgr._missions[f"m{i}"] = Mission(
            id=f"m{i}",
            task=f"task {i}",
            label=f"label-{i}",
            role="general",
            status=status,
            created_at=now,
        )

    tool = MissionListTool(manager=mgr)
    result = await tool.execute(status_filter="all")
    assert result.success is True
    assert "m0" in result.output
    assert "m1" in result.output
    assert "m2" in result.output


async def test_mission_list_tool_filters_by_status() -> None:
    """mission_list with status_filter should return only matching missions."""
    mgr = _make_manager()
    now = datetime.now(timezone.utc)
    mgr._missions["r1"] = Mission(
        id="r1",
        task="t",
        label="running",
        role="g",
        status=MissionStatus.RUNNING,
        created_at=now,
    )
    mgr._missions["c1"] = Mission(
        id="c1",
        task="t",
        label="done",
        role="g",
        status=MissionStatus.COMPLETED,
        created_at=now,
    )

    tool = MissionListTool(manager=mgr)
    result = await tool.execute(status_filter="active")
    assert "r1" in result.output
    assert "c1" not in result.output


# ---------------------------------------------------------------------------
# MissionCancelTool
# ---------------------------------------------------------------------------


async def test_mission_cancel_tool_success() -> None:
    """mission_cancel should return ok when cancel signal is sent."""

    class _SlowProvider:
        async def chat(self, **_kwargs: object) -> LLMResponse:
            await asyncio.sleep(10)
            return LLMResponse(content="never")

        def get_default_model(self) -> str:
            return "openai/gpt-4.1"

    bus = _make_bus()
    mgr = MissionManager(
        sub_agent_config=SubAgentConfig(
            workspace=Path("/tmp/test-workspace"),
            model="openai/gpt-4.1",
        ),
        provider=_SlowProvider(),  # type: ignore[arg-type]
        bus=bus,
        max_iterations=2,
        delegation_tools=_default_delegation_tools(),
    )
    mission = await mgr.start("slow task")
    # Yield to event loop so background task starts running
    await asyncio.sleep(0)

    tool = MissionCancelTool(manager=mgr)
    result = await tool.execute(mission_id=mission.id)
    assert result.success is True
    assert "cancel" in result.output.lower()

    # Cleanup by awaiting the task directly (Pattern A)
    for task in list(mgr._running_tasks.values()):
        try:
            _ = await task
        except asyncio.CancelledError:
            pass  # Expected when mission is cancelled; safe to ignore


async def test_mission_cancel_tool_not_found() -> None:
    """mission_cancel should fail for unknown mission ID."""
    mgr = _make_manager()
    tool = MissionCancelTool(manager=mgr)
    result = await tool.execute(mission_id="nope")
    assert result.success is False


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


async def test_mission_emits_langfuse_span() -> None:
    """_execute_mission should wrap execution in a langfuse span."""
    mgr = _make_manager(responses=[LLMResponse(content="done")])

    with patch("nanobot.coordination.mission.langfuse_span") as mock_span:
        # Make the mock work as an async context manager
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_span.return_value = ctx

        await mgr.start(task="test span")
        # Await the background task directly (Pattern A)
        for task in list(mgr._running_tasks.values()):
            _ = await task

        mock_span.assert_called_once()
        call_kwargs = mock_span.call_args.kwargs
        assert call_kwargs["name"] == "mission"
        assert "mission_id" in call_kwargs["metadata"]


async def test_mission_scores_grounding() -> None:
    """Completed mission should score grounding confidence via langfuse."""
    mgr = _make_manager(
        responses=[
            LLMResponse(
                content="",
                tool_calls=[ToolCallRequest(id="t1", name="echo", arguments={"text": "hi"})],
            ),
            LLMResponse(content="found it"),
        ],
    )

    with patch("nanobot.coordination.mission.score_current_trace") as mock_score:
        await mgr.start(task="grounding test")
        # Await the background task directly (Pattern A)
        for task in list(mgr._running_tasks.values()):
            _ = await task

        mock_score.assert_called_once()
        call_kwargs = mock_score.call_args.kwargs
        assert call_kwargs["name"] == "mission_grounded"
        assert call_kwargs["value"] == 1.0


async def test_mission_sets_trace_context() -> None:
    """Mission execution should set TraceContext with the mission ID."""
    mgr = _make_manager(responses=[LLMResponse(content="ok")])

    with patch("nanobot.coordination.mission.TraceContext") as mock_tc:
        mission = await mgr.start(task="trace test")
        # Await the background task directly (Pattern A)
        for task in list(mgr._running_tasks.values()):
            _ = await task

        mock_tc.set.assert_called_once()
        call_kwargs = mock_tc.set.call_args.kwargs
        assert call_kwargs["request_id"] == mission.id


# ---------------------------------------------------------------------------
# Phase 4 — MCP tool sharing
# ---------------------------------------------------------------------------


class _FakeMCPTool(Tool):
    """Pretend MCP tool for testing registry sharing."""

    def __init__(self, tool_name: str = "mcp_server_search") -> None:
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake mcp tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult.ok("mcp result")


def test_mcp_tools_in_mission_registry() -> None:
    """MCP tools should appear in the isolated mission registry."""
    mgr = _make_manager()
    mgr.mcp_tools = [_FakeMCPTool("mcp_srv_search")]
    role = AgentRoleConfig(name="general", description="General")
    tools = mgr._build_tool_registry(role)
    assert "mcp_srv_search" in tools._tools


def test_mcp_tools_filtered_by_denied() -> None:
    """MCP tools in denied_tools should be removed."""
    mgr = _make_manager()
    mgr.mcp_tools = [_FakeMCPTool("mcp_srv_search")]
    role = AgentRoleConfig(name="safe", description="Safe", denied_tools=["mcp_srv_search"])
    tools = mgr._build_tool_registry(role)
    assert "mcp_srv_search" not in tools._tools


def test_mcp_tools_filtered_by_allowed() -> None:
    """MCP tools not in allowed_tools should be removed."""
    mgr = _make_manager()
    mgr.mcp_tools = [_FakeMCPTool("mcp_srv_search")]
    role = AgentRoleConfig(name="minimal", description="Minimal", allowed_tools=["read_file"])
    tools = mgr._build_tool_registry(role)
    assert "mcp_srv_search" not in tools._tools
    assert "read_file" in tools._tools


def test_mcp_tools_pass_through_allowed() -> None:
    """MCP tools listed in allowed_tools survive the filter."""
    mgr = _make_manager()
    mgr.mcp_tools = [_FakeMCPTool("mcp_srv_search")]
    role = AgentRoleConfig(
        name="full", description="Full", allowed_tools=["read_file", "mcp_srv_search"]
    )
    tools = mgr._build_tool_registry(role)
    assert "mcp_srv_search" in tools._tools
    assert "read_file" in tools._tools


# ---------------------------------------------------------------------------
# Phase 4 — MissionConfig / max_concurrent
# ---------------------------------------------------------------------------


async def test_max_concurrent_rejects_excess() -> None:
    """Starting a mission beyond max_concurrent should return ToolResult.fail."""
    mgr = _make_manager(
        responses=[LLMResponse(content="busy")] * 5,
    )
    mgr.max_concurrent = 2

    # Start two missions (fills capacity)
    await mgr.start(task="task-1")
    await mgr.start(task="task-2")

    tool = MissionStartTool(mgr)
    result = await tool.execute(task="task-3")
    assert not result.success
    assert "Maximum concurrent missions" in result.output


async def test_max_concurrent_allows_after_completion() -> None:
    """Once a mission completes, a new slot opens up."""
    mgr = _make_manager(
        responses=[LLMResponse(content="done")] * 5,
    )
    mgr.max_concurrent = 1

    first_mission = await mgr.start(task="first")
    # Await the background task so the slot is freed (Pattern A)
    bg_task = mgr._running_tasks.get(first_mission.id)
    if bg_task is not None:
        _ = await bg_task

    # Slot should be open now
    mission = await mgr.start(task="second")
    assert mission.id  # successfully started


async def test_result_max_chars_configurable() -> None:
    """_deliver_result should respect the configured result_max_chars."""
    mgr = _make_manager()
    mgr.result_max_chars = 100

    mission = Mission(
        id="trunc",
        task="test",
        label="test",
        role="general",
        status=MissionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        result="x" * 200,
        grounded=True,
        tools_used=["read_file"],
    )

    await mgr._deliver_result(mission)

    call_args = mgr.bus.publish_outbound.call_args
    body = call_args[0][0].content
    assert len(body) <= 100


def test_mission_config_defaults() -> None:
    """MissionConfig should have the expected default values."""
    from nanobot.config.mission import MissionConfig

    cfg = MissionConfig()
    assert cfg.max_concurrent == 3
    assert cfg.max_iterations == 15
    assert cfg.result_max_chars == 4000


def test_config_propagates_mission() -> None:
    """AgentConfig should propagate nested mission config fields."""
    from nanobot.config.agent import AgentConfig
    from nanobot.config.mission import MissionConfig

    config = AgentConfig(
        workspace="/tmp/test",
        model="test",
        mission=MissionConfig(max_concurrent=5, max_iterations=20, result_max_chars=8000),
    )
    assert config.mission.max_concurrent == 5
    assert config.mission.max_iterations == 20
    assert config.mission.result_max_chars == 8000
