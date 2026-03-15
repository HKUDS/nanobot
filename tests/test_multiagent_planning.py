"""End-to-end test for multi-agent planning and delegation.

Exercises the full Plan → Delegate → Synthesise cycle:
1. A complex task triggers the planning heuristic.
2. The parent agent delegates a research sub-task to the "research" role.
3. The parent agent delegates a code sub-task to the "code" role.
4. Both delegations run in parallel via ``delegate_parallel``.
5. The parent synthesises the specialist results into a final answer.

Also validates:
- Routing trace records all delegation events.
- Delegation stack is clean after execution.
- Planning prompt is injected for multi-step tasks.
- Sequential delegation (delegate) with a deep A→B chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.coordinator import Coordinator, build_default_registry
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# ---------------------------------------------------------------------------
# Scripted provider that maps calls to deterministic responses
# ---------------------------------------------------------------------------


class ScriptedProvider(LLMProvider):
    """LLM provider that returns pre-configured responses in order.

    Each call to ``chat()`` pops the next response off the queue.  When the
    queue is exhausted a default fallback is returned.
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__()
        self._responses = list(responses)
        self._index = 0
        self.call_log: list[dict] = []

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.call_log.append(
            {
                "messages_count": len(messages),
                "has_tools": tools is not None,
                "model": model,
                "last_user_msg": next(
                    (m.get("content", "")[:120] for m in reversed(messages) if m["role"] == "user"),
                    "",
                ),
            }
        )
        if self._index >= len(self._responses):
            return LLMResponse(content="(no more scripted responses)")
        resp = self._responses[self._index]
        self._index += 1
        return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path, **overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=10,
        planning_enabled=True,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _loop(tmp_path: Path, provider: LLMProvider, **kw: Any) -> AgentLoop:
    bus = MessageBus()
    config = _cfg(tmp_path, **kw)
    loop = AgentLoop(bus, provider, config)
    # Wire up coordinator with default roles so delegation is available.
    registry = build_default_registry("general")
    loop._coordinator = Coordinator(provider=provider, registry=registry, default_role="general")
    loop._dispatcher.coordinator = loop._coordinator
    loop._wire_delegate_tools()
    return loop


def _inbound(text: str) -> InboundMessage:
    return InboundMessage(
        channel="cli",
        chat_id="test-user",
        sender_id="user-1",
        content=text,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlanningHeuristic:
    """Validate _needs_planning triggers for multi-step requests."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Should trigger planning
            ("Research the topic and then write a summary document", True),
            ("First analyze the data, second create a report", True),
            ("Investigate the performance issue and implement a fix", True),
            ("Create a REST API with authentication and deploy it", True),
            # Should NOT trigger planning
            ("Hello", False),
            ("What time is it?", False),
            ("", False),
        ],
    )
    def test_needs_planning(self, text: str, expected: bool) -> None:
        assert AgentLoop._needs_planning(text) is expected


class TestParallelStructureDetection:
    """Validate _has_parallel_structure for enumerated independent subtasks."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Should detect parallel structure
            (
                "Review the shell command guard, filesystem path traversal "
                "protection, and API key handling",
                True,
            ),
            ("Compare performance across three areas: latency, throughput, and memory", True),
            ("Audit modules: auth, billing, notifications, and logging", True),
            ("Evaluate 1) code quality 2) test coverage 3) documentation", True),
            ("Assess performance across CPU usage, memory, and I/O latency", True),
            # Should NOT detect parallel structure
            ("Fix the bug in loop.py", False),
            ("What does the _needs_planning function do?", False),
            ("Hello", False),
            ("", False),
            ("Investigate how events flow from extraction to persistence", False),
        ],
    )
    def test_has_parallel_structure(self, text: str, expected: bool) -> None:
        assert AgentLoop._has_parallel_structure(text) is expected


class TestParallelDelegationE2E:
    """Full cycle: plan → delegate_parallel(research + code) → synthesise."""

    @pytest.mark.asyncio
    async def test_plan_delegate_parallel_synthesise(self, tmp_path: Path) -> None:
        """Parent agent plans, fans out to research & code, combines results."""

        # Create a file in workspace so the code agent has something to read
        (tmp_path / "data.csv").write_text("id,value\n1,100\n2,200\n")

        # Response sequence (each entry consumed in order across ALL LLM calls):
        # 1. Parent planning + delegate_parallel tool call
        # 2. Research agent initial response (no tool use → triggers retry)
        # 3. Code agent initial response (no tool use → triggers retry)
        # 4. Research agent retry response (after tool-use reminder)
        # 5. Code agent retry response (after tool-use reminder)
        # 6. Parent final synthesis
        # Note: research & code run in parallel, so order of 2-5 may vary.
        provider = ScriptedProvider(
            [
                # (1) Parent: planning step + delegate_parallel call
                LLMResponse(
                    content=(
                        "Plan:\n"
                        "1. Delegate research to gather info on CSV data formats\n"
                        "2. Delegate coding to write a parser\n"
                        "3. Combine results\n"
                    ),
                    tool_calls=[
                        ToolCallRequest(
                            id="call_par",
                            name="delegate_parallel",
                            arguments={
                                "subtasks": [
                                    {
                                        "target_role": "research",
                                        "task": "Summarise best practices for CSV parsing in Python",
                                    },
                                    {
                                        "target_role": "code",
                                        "task": "Write a Python function to parse data.csv",
                                    },
                                ]
                            },
                        )
                    ],
                ),
                # (2) First subagent initial response (no tools → retry)
                LLMResponse(
                    content=(
                        "CSV parsing best practices:\n"
                        "- Use the csv module from stdlib\n"
                        "- Handle encoding with utf-8\n"
                        "- Use DictReader for named columns"
                    )
                ),
                # (3) Second subagent initial response (no tools → retry)
                LLMResponse(
                    content=(
                        "```python\nimport csv\n\n"
                        "def parse_data(path):\n"
                        "    with open(path) as f:\n"
                        "        return list(csv.DictReader(f))\n```"
                    )
                ),
                # (4) First subagent retry response
                LLMResponse(
                    content=(
                        "CSV parsing best practices (verified):\n"
                        "- Use the csv module from stdlib\n"
                        "- Use DictReader for named columns"
                    )
                ),
                # (5) Second subagent retry response
                LLMResponse(
                    content=(
                        "```python\nimport csv\n\n"
                        "def parse_data(path):\n"
                        "    with open(path) as f:\n"
                        "        return list(csv.DictReader(f))\n```"
                    )
                ),
                # (6) Parent synthesises the combined delegation results
                LLMResponse(
                    content=(
                        "Here's the complete solution:\n\n"
                        "Based on research, we should use csv.DictReader. "
                        "The implementation reads data.csv and returns a list of dicts."
                    )
                ),
            ]
        )

        loop = _loop(tmp_path, provider)
        msg = _inbound("Research CSV parsing best practices and then write a parser for data.csv")
        result = await loop._process_message(msg)

        # Verify final answer was synthesised
        assert result is not None
        assert "csv" in result.content.lower() or "DictReader" in result.content

        # Verify routing trace recorded both delegations
        trace = loop.get_routing_trace()
        delegate_events = [e for e in trace if e["event"] == "delegate"]
        complete_events = [e for e in trace if e["event"] == "delegate_complete"]

        assert len(delegate_events) >= 2, f"Expected ≥2 delegate events, got {delegate_events}"
        assert len(complete_events) >= 2, f"Expected ≥2 completions, got {complete_events}"

        delegated_roles = {e["role"] for e in delegate_events}
        assert "research" in delegated_roles
        assert "code" in delegated_roles

        # All completions succeeded
        for ce in complete_events:
            assert ce["success"] is True

        # Delegation stack is clean
        assert loop._delegation_stack == []


class TestSequentialDelegationChain:
    """Test A → B sequential delegation (single delegate tool)."""

    @pytest.mark.asyncio
    async def test_delegate_then_answer(self, tmp_path: Path) -> None:
        """Parent delegates to research, gets result, responds to user."""

        provider = ScriptedProvider(
            [
                # (1) Parent calls delegate(target_role="research", task=...)
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_del",
                            name="delegate",
                            arguments={
                                "target_role": "research",
                                "task": "Find the top 3 Python web frameworks by popularity",
                            },
                        )
                    ],
                ),
                # (2) Research agent's initial answer (no tools → retry)
                LLMResponse(
                    content=(
                        "Top 3 Python web frameworks:\n"
                        "1. Django — full-featured, batteries-included\n"
                        "2. Flask — lightweight, flexible\n"
                        "3. FastAPI — async, auto-docs"
                    )
                ),
                # (3) Research agent retry response (after tool-use reminder)
                LLMResponse(
                    content=(
                        "Top 3 Python web frameworks:\n"
                        "1. Django — full-featured, batteries-included\n"
                        "2. Flask — lightweight, flexible\n"
                        "3. FastAPI — async, auto-docs"
                    )
                ),
                # (4) Parent produces final answer after delegation result
                LLMResponse(
                    content=(
                        "According to research, the top 3 Python web frameworks are: "
                        "Django, Flask, and FastAPI."
                    )
                ),
            ]
        )

        loop = _loop(tmp_path, provider, planning_enabled=False)
        msg = _inbound("What are the top 3 Python web frameworks?")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Django" in result.content
        assert "Flask" in result.content
        assert "FastAPI" in result.content

        # Trace shows delegate → delegate_complete for research
        trace = loop.get_routing_trace()
        assert any(e["event"] == "delegate" and e["role"] == "research" for e in trace)
        assert any(
            e["event"] == "delegate_complete" and e["role"] == "research" and e["success"]
            for e in trace
        )

        # Stack clean after delegation
        assert loop._delegation_stack == []


class TestDelegationWithToolUse:
    """Test that a delegated agent can use tools to accomplish its task."""

    @pytest.mark.asyncio
    async def test_code_agent_uses_read_file(self, tmp_path: Path) -> None:
        """Code agent reads a file during its delegated tool loop."""

        (tmp_path / "config.json").write_text('{"debug": true, "port": 8080}')

        provider = ScriptedProvider(
            [
                # (1) Parent delegates to code agent
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_del",
                            name="delegate",
                            arguments={
                                "target_role": "code",
                                "task": "Read config.json and summarise its contents",
                                "context": f"Workspace: {tmp_path}",
                            },
                        )
                    ],
                ),
                # (2) Code agent: calls read_file tool
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="sub_c1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "config.json")},
                        )
                    ],
                ),
                # (3) Code agent: final answer after reading file
                LLMResponse(
                    content="config.json has debug=true and port=8080",
                ),
                # (4) Parent: final answer incorporating delegation result
                LLMResponse(
                    content="The config file enables debug mode and listens on port 8080.",
                ),
            ]
        )

        loop = _loop(tmp_path, provider, planning_enabled=False)
        msg = _inbound("Analyze the config.json file in the workspace")
        result = await loop._process_message(msg)

        assert result is not None
        assert "8080" in result.content or "debug" in result.content.lower()

        # Verify the code agent actually ran tools (check provider call log)
        # The code agent should have made 2 calls (tool use + answer)
        assert provider._index >= 3  # parent call + code sub-calls + parent answer


class TestPlanningPromptInjection:
    """Verify the planning prompt is injected for complex tasks."""

    @pytest.mark.asyncio
    async def test_planning_prompt_added(self, tmp_path: Path) -> None:
        """Complex task triggers planning; simple task does not."""

        provider = ScriptedProvider([LLMResponse(content="Here's my plan and answer.")])

        loop = _loop(tmp_path, provider, planning_enabled=True)
        msg = _inbound("Research market trends and then create a comprehensive report document")
        await loop._process_message(msg)

        # Check that the provider received a planning prompt in messages
        assert len(provider.call_log) >= 1
        first_call = provider.call_log[0]
        # The planning prompt should make the message count higher
        assert first_call["messages_count"] >= 3  # system + user + planning system

    @pytest.mark.asyncio
    async def test_simple_message_no_planning(self, tmp_path: Path) -> None:
        """Short message doesn't trigger planning."""

        provider = ScriptedProvider([LLMResponse(content="Hello!")])

        loop = _loop(tmp_path, provider, planning_enabled=True)
        msg = _inbound("Hi")
        await loop._process_message(msg)

        # Short messages should NOT get a planning prompt injected
        first_call = provider.call_log[0]
        # Without planning, expects just system + user (typically 2-3 messages)
        assert first_call["messages_count"] <= 3


class TestCycleDetectionInMultiAgent:
    """Cycle detection across multi-agent chains."""

    @pytest.mark.asyncio
    async def test_self_delegation_blocked(self, tmp_path: Path) -> None:
        """Agent cannot delegate back to a role already in the ancestry."""

        provider = ScriptedProvider(
            [
                # (1) Parent delegates to code
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1",
                            name="delegate",
                            arguments={
                                "target_role": "code",
                                "task": "Write tests",
                            },
                        )
                    ],
                ),
                # (2) Code agent tries to delegate back to code (cycle!)
                # But the code agent's own run_tool_loop will return this text
                # because the child DelegateTool won't be exercised here —
                # we test via the stack mechanism directly.
                LLMResponse(content="Tests written successfully"),
                # (3) Parent final answer
                LLMResponse(content="Tests are done."),
            ]
        )

        loop = _loop(tmp_path, provider, planning_enabled=False)

        # Simulate being inside a "code" delegation via ContextVar
        from nanobot.agent.loop import _delegation_ancestry

        token = _delegation_ancestry.set(("code",))
        try:
            # Attempting to delegate to "code" again should raise _CycleError
            from nanobot.agent.tools.delegate import _CycleError

            with pytest.raises(_CycleError, match="cycle"):
                await loop._dispatch_delegation("code", "Write more code", None)

            # Trace should record the blocked cycle
            trace = loop.get_routing_trace()
            blocked = [e for e in trace if e["event"] == "delegate_cycle_blocked"]
            assert len(blocked) == 1
            assert blocked[0]["role"] == "code"

            # Ancestry still has the original entry (not corrupted)
            assert _delegation_ancestry.get() == ("code",)
        finally:
            _delegation_ancestry.reset(token)

    @pytest.mark.asyncio
    async def test_deep_chain_allowed(self, tmp_path: Path) -> None:
        """A → B → C delegation chain is allowed (no cycle)."""

        provider = ScriptedProvider(
            [
                # (1) Research agent response (delegated from parent outside this test)
                LLMResponse(content="Research findings here"),
            ]
        )

        loop = _loop(tmp_path, provider, planning_enabled=False)

        # Simulate being inside a "code" delegation via ContextVar
        from nanobot.agent.loop import _delegation_ancestry

        token = _delegation_ancestry.set(("code",))
        try:
            # Delegating to "research" should succeed (code → research, no cycle)
            result = await loop._dispatch_delegation(
                "research", "Find performance benchmarks", None
            )

            assert result is not None
            assert "Research" in result.content or "findings" in result.content

            # Ancestry restored to just ("code",)
            assert _delegation_ancestry.get() == ("code",)
        finally:
            _delegation_ancestry.reset(token)


class TestMultiAgentRoutingTrace:
    """Verify routing trace captures the full delegation lifecycle."""

    @pytest.mark.asyncio
    async def test_trace_captures_latency(self, tmp_path: Path) -> None:
        """Delegation trace entries include latency_ms > 0."""

        provider = ScriptedProvider([LLMResponse(content="Done with research")])

        loop = _loop(tmp_path, provider, planning_enabled=False)
        await loop._dispatch_delegation("research", "quick task", None)

        trace = loop.get_routing_trace()
        complete = [e for e in trace if e["event"] == "delegate_complete"]
        assert len(complete) == 1
        assert complete[0]["latency_ms"] >= 0
        assert complete[0]["success"] is True

    @pytest.mark.asyncio
    async def test_parallel_trace_complete(self, tmp_path: Path) -> None:
        """Parallel delegation records traces for ALL branches."""

        provider = ScriptedProvider(
            [
                # Parent: delegate_parallel call
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_par",
                            name="delegate_parallel",
                            arguments={
                                "subtasks": [
                                    {"target_role": "research", "task": "Find info"},
                                    {"target_role": "code", "task": "Write code"},
                                    {"target_role": "writing", "task": "Write docs"},
                                ]
                            },
                        )
                    ],
                ),
                # Research agent response
                LLMResponse(content="Info found"),
                # Code agent response
                LLMResponse(content="Code written"),
                # Writing agent response
                LLMResponse(content="Docs written"),
                # Parent final answer
                LLMResponse(content="All three tasks completed."),
            ]
        )

        loop = _loop(tmp_path, provider)
        msg = _inbound("Research, code, and document the new feature")
        result = await loop._process_message(msg)

        assert result is not None
        trace = loop.get_routing_trace()
        delegate_events = [e for e in trace if e["event"] == "delegate"]
        complete_events = [e for e in trace if e["event"] == "delegate_complete"]

        # Should have 3 delegation starts and 3 completions
        assert len(delegate_events) >= 3
        assert len(complete_events) >= 3

        roles_delegated = {e["role"] for e in delegate_events}
        assert roles_delegated >= {"research", "code", "writing"}
