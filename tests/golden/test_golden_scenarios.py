"""Golden tests for agent loop orchestration behavior.

These tests freeze the *agent's* behavior — not the LLM's.  The LLM is
fully scripted; the assertions verify what the **agent loop** actually does
with those scripted responses:

- What messages does the agent send TO the LLM? (system prompt, tool results,
  nudges, planning injections, failure-strategy prompts)
- What real side effects did tool execution produce? (files read/written)
- How many loop iterations were consumed?
- Which orchestration mechanisms fired? (compression, plan enforcement,
  nudge-for-final-answer, max-iterations guard, consecutive-error fallback)

If a golden test fails after a refactor, the orchestration behavior changed
and the change must be intentional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ScriptedProvider(LLMProvider):
    """LLM provider that returns pre-configured responses in order.

    Captures the full ``messages`` list for each call so tests can inspect
    exactly what the agent loop assembled before calling the LLM.
    """

    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self._index = 0
        self.call_log: list[dict[str, Any]] = []

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.call_log.append(
            {
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "model": model,
            }
        )
        if self._index >= len(self._responses):
            return LLMResponse(content="(no more scripted responses)")
        resp = self._responses[self._index]
        self._index += 1
        return resp


def _make_config(tmp_path: Path, **overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_loop(tmp_path: Path, provider: LLMProvider, **config_overrides: Any) -> AgentLoop:
    bus = MessageBus()
    config = _make_config(tmp_path, **config_overrides)
    return AgentLoop(bus, provider, config)


def _make_inbound(text: str) -> InboundMessage:
    return InboundMessage(
        channel="cli",
        chat_id="golden-test",
        sender_id="user-1",
        content=text,
    )


def _roles(messages: list[dict[str, Any]]) -> list[str]:
    """Extract the role sequence from a message list."""
    return [m["role"] for m in messages]


def _tool_result_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract only tool-result messages from a message list."""
    return [m for m in messages if m.get("role") == "tool"]


def _system_messages(messages: list[dict[str, Any]]) -> list[str]:
    """Extract content of system-role messages."""
    return [m["content"] for m in messages if m.get("role") == "system"]


# ---------------------------------------------------------------------------
# Golden 1: Single-turn Q&A — agent passes through without tool defs on retry
# ---------------------------------------------------------------------------


class TestGoldenSingleTurn:
    """A direct text answer should produce exactly one LLM call.

    Verifies the agent:
    - Sends a system prompt + user message to the LLM
    - Does NOT strip/rewrite the LLM's text content
    - Consumes exactly 1 iteration
    - Does not inject nudge, planning, or reflection prompts
    """

    @pytest.mark.asyncio
    async def test_one_llm_call_no_orchestration_overhead(self, tmp_path: Path):
        provider = ScriptedProvider([LLMResponse(content="Paris.")])
        loop = _make_loop(tmp_path, provider)

        result = await loop._process_message(_make_inbound("Capital of France?"))

        # Exactly one LLM call
        assert len(provider.call_log) == 1
        assert result is not None
        assert result.content == "Paris."

        # The agent sent a system prompt and a user message
        sent_messages = provider.call_log[0]["messages"]
        assert sent_messages[0]["role"] == "system"  # system prompt exists
        assert any(
            m["role"] == "user" and "Capital of France?" in str(m.get("content", ""))
            for m in sent_messages
        ), "Agent must forward the user's message to the LLM"

        # Tool definitions were offered (agent provides tools on first call)
        assert provider.call_log[0]["tools"] is not None


# ---------------------------------------------------------------------------
# Golden 2: Tool execution — agent injects real tool output into LLM context
# ---------------------------------------------------------------------------


class TestGoldenToolResultInjection:
    """When the LLM requests read_file, the agent must:
    1. Actually execute the tool (read the real file)
    2. Inject the real file contents as a tool-result message
    3. Call the LLM a second time with the tool result in context
    """

    @pytest.mark.asyncio
    async def test_real_file_content_injected(self, tmp_path: Path):
        secret = "db_password=hunter2"
        (tmp_path / "secrets.txt").write_text(secret)

        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "secrets.txt")},
                        )
                    ],
                ),
                LLMResponse(content="Done."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("Read secrets.txt"))

        # Two LLM calls: initial + after tool result
        assert len(provider.call_log) == 2

        # The second LLM call must contain a tool-result message with the
        # REAL file content (not a scripted string)
        second_call_msgs = provider.call_log[1]["messages"]
        tool_results = _tool_result_messages(second_call_msgs)
        assert len(tool_results) >= 1, "Agent must inject tool result into context"
        assert secret in tool_results[0]["content"], (
            "Tool result must contain actual file content, not a canned string"
        )

    @pytest.mark.asyncio
    async def test_failed_tool_produces_error_in_context(self, tmp_path: Path):
        """When a tool fails, the agent injects the error as a tool result."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "no_such_file.txt")},
                        )
                    ],
                ),
                LLMResponse(content="File not found."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("read it"))

        second_call_msgs = provider.call_log[1]["messages"]
        tool_results = _tool_result_messages(second_call_msgs)
        assert len(tool_results) >= 1
        result_text = tool_results[0]["content"].lower()
        assert "error" in result_text or "not found" in result_text or "no such" in result_text, (
            "Failed tool execution must produce an error message in context"
        )

    @pytest.mark.asyncio
    async def test_failure_strategy_prompt_injected(self, tmp_path: Path):
        """After a tool failure, the agent injects a failure-strategy system prompt."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "missing.txt")},
                        )
                    ],
                ),
                LLMResponse(content="I'll try something else."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("read missing.txt"))

        # Inspect what was sent for the second LLM call
        second_call_systems = _system_messages(provider.call_log[1]["messages"])
        # The agent should have injected a failure-strategy reflection prompt
        assert any(
            "fail" in s.lower() or "alternative" in s.lower() or "strateg" in s.lower()
            for s in second_call_systems
        ), "Agent must inject a failure-strategy prompt after tool errors"


# ---------------------------------------------------------------------------
# Golden 3: Multi-step chain — message history grows correctly
# ---------------------------------------------------------------------------


class TestGoldenMultiStepHistory:
    """A two-tool chain must produce three LLM calls with correctly
    growing message histories.
    """

    @pytest.mark.asyncio
    async def test_message_history_accumulates(self, tmp_path: Path):
        (tmp_path / "data.csv").write_text("a,b,c")
        provider = ScriptedProvider(
            [
                # Step 1: list dir
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="list_dir",
                            arguments={"path": str(tmp_path)},
                        )
                    ],
                ),
                # Step 2: read specific file
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc2",
                            name="read_file",
                            arguments={"path": str(tmp_path / "data.csv")},
                        )
                    ],
                ),
                # Step 3: final answer
                LLMResponse(content="CSV has three columns."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("What's in the workspace?"))

        assert result is not None
        assert len(provider.call_log) == 3

        # Each successive LLM call gets a LONGER context
        len1 = len(provider.call_log[0]["messages"])
        len2 = len(provider.call_log[1]["messages"])
        len3 = len(provider.call_log[2]["messages"])
        assert len2 > len1, "Second call must include tool result from first"
        assert len3 > len2, "Third call must include tool result from second"

        # The second call should contain a tool-result with actual dir listing
        second_tool_results = _tool_result_messages(provider.call_log[1]["messages"])
        assert any("data.csv" in tr["content"] for tr in second_tool_results), (
            "list_dir result must contain actual directory contents"
        )

        # The third call should contain a tool-result with actual file content
        third_tool_results = _tool_result_messages(provider.call_log[2]["messages"])
        assert any("a,b,c" in tr["content"] for tr in third_tool_results), (
            "read_file result must contain actual file content"
        )


# ---------------------------------------------------------------------------
# Golden 4: Nudge for final answer — orchestration mechanism
# ---------------------------------------------------------------------------


class TestGoldenNudgeForFinalAnswer:
    """When the LLM returns empty content after tool use, the agent must
    inject a 'produce your final answer' nudge and retry WITHOUT tool defs.
    """

    @pytest.mark.asyncio
    async def test_nudge_injected_and_tools_disabled(self, tmp_path: Path):
        (tmp_path / "f.txt").write_text("data")
        provider = ScriptedProvider(
            [
                # Tool call
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "f.txt")},
                        )
                    ],
                ),
                # LLM returns empty — should trigger nudge
                LLMResponse(content=None),
                # After nudge, LLM answers
                LLMResponse(content="The file contains data."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("read f.txt"))

        assert result is not None
        assert result.content == "The file contains data."
        assert len(provider.call_log) == 3

        # The third call should have tools=None (agent disables tools after nudge)
        assert provider.call_log[2]["tools"] is None, (
            "After nudge, agent must disable tool definitions to force text answer"
        )

        # A nudge system message should appear in the third call's context
        third_systems = _system_messages(provider.call_log[2]["messages"])
        assert any("final answer" in s.lower() for s in third_systems), (
            "Agent must inject a nudge asking for final answer"
        )


# ---------------------------------------------------------------------------
# Golden 5: Max iterations guard — agent stops and explains
# ---------------------------------------------------------------------------


class TestGoldenMaxIterationsGuard:
    """Agent must stop after max_iterations and produce a specific fallback
    message mentioning the limit — this tests the loop's safety mechanism.
    """

    @pytest.mark.asyncio
    async def test_iteration_limit_produces_explanation(self, tmp_path: Path):
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"tc{i}",
                            name="list_dir",
                            arguments={"path": str(tmp_path)},
                        )
                    ],
                )
                for i in range(10)
            ]
        )
        loop = _make_loop(tmp_path, provider, max_iterations=2)
        result = await loop._process_message(_make_inbound("loop forever"))

        assert result is not None
        # The fallback message must mention the iteration limit
        assert "maximum" in result.content.lower() or "2" in result.content
        # Agent should NOT have consumed all 10 scripted responses
        assert provider._index <= 3  # 2 iterations + possible nudge


# ---------------------------------------------------------------------------
# Golden 6: Write tool side effect — agent's tool execution changes the world
# ---------------------------------------------------------------------------


class TestGoldenWriteToolSideEffect:
    """The agent's tool execution must produce real filesystem side effects.
    This verifies that the loop actually runs tools, not just passes through.
    """

    @pytest.mark.asyncio
    async def test_write_file_creates_real_file(self, tmp_path: Path):
        target = tmp_path / "output.txt"
        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="write_file",
                            arguments={
                                "path": str(target),
                                "content": "hello from the agent",
                            },
                        )
                    ],
                ),
                LLMResponse(content="File written."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        await loop._process_message(_make_inbound("create output.txt"))

        # The REAL file must exist with the REAL content
        assert target.exists(), "write_file tool must create the actual file"
        assert target.read_text() == "hello from the agent"


# ---------------------------------------------------------------------------
# Golden 7: Consecutive LLM errors — graceful degradation
# ---------------------------------------------------------------------------


class TestGoldenConsecutiveErrorFallback:
    """Three consecutive LLM error responses must trigger graceful fallback.
    This tests the agent's error-counting and recovery mechanism.
    """

    @pytest.mark.asyncio
    async def test_three_errors_produce_fallback(self, tmp_path: Path):
        provider = ScriptedProvider(
            [
                LLMResponse(content="err", finish_reason="error"),
                LLMResponse(content="err", finish_reason="error"),
                LLMResponse(content="err", finish_reason="error"),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("hi"))

        assert result is not None
        assert "trouble" in result.content.lower() or "try again" in result.content.lower()
        # The agent should have called the LLM 3 times before giving up
        assert len(provider.call_log) == 3


# ---------------------------------------------------------------------------
# Golden 8: Tool failure → reflect → retry → success
# ---------------------------------------------------------------------------


class TestGoldenToolFailureRecovery:
    """When a tool fails, the agent should inject a reflection/strategy prompt,
    then succeed on a different approach.  This tests the recovery path.
    """

    @pytest.mark.asyncio
    async def test_recover_after_initial_failure(self, tmp_path: Path):
        # First attempt reads a missing file; second reads an existing one
        (tmp_path / "backup.txt").write_text("recovered data")
        provider = ScriptedProvider(
            [
                # Step 1: try to read missing file
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "gone.txt")},
                        )
                    ],
                ),
                # Step 2: agent reflects and tries backup
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc2",
                            name="read_file",
                            arguments={"path": str(tmp_path / "backup.txt")},
                        )
                    ],
                ),
                # Step 3: final answer
                LLMResponse(content="Found the data in backup.txt."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("find the data"))

        assert result is not None
        assert "backup" in result.content.lower() or "found" in result.content.lower()
        assert len(provider.call_log) == 3

        # The second call should contain a failure-strategy prompt
        second_systems = _system_messages(provider.call_log[1]["messages"])
        assert any(
            "fail" in s.lower() or "alternative" in s.lower() or "strateg" in s.lower()
            for s in second_systems
        ), "Agent must inject recovery strategy prompt after tool failure"

        # The third call must include the successful tool result
        third_tool_results = _tool_result_messages(provider.call_log[2]["messages"])
        assert any("recovered data" in tr["content"] for tr in third_tool_results), (
            "Successful retry result must appear in context"
        )


# ---------------------------------------------------------------------------
# Golden 9: Planning prompt injection
# ---------------------------------------------------------------------------


class TestGoldenPlanningInjection:
    """When planning_enabled=True and the message looks like a multi-step task,
    the agent should inject a planning prompt into the LLM context.
    """

    @pytest.mark.asyncio
    async def test_planning_prompt_present_for_complex_task(self, tmp_path: Path):
        provider = ScriptedProvider(
            [
                LLMResponse(content="1. Read the file\n2. Analyze\n3. Report\n\nDone."),
            ]
        )
        loop = _make_loop(tmp_path, provider, planning_enabled=True)
        await loop._process_message(
            _make_inbound(
                "Read all source files in the project, check for security issues, "
                "and write a detailed report."
            )
        )

        assert len(provider.call_log) >= 1
        # The first call should have a planning-related system prompt
        first_systems = _system_messages(provider.call_log[0]["messages"])
        all_system_text = " ".join(first_systems).lower()
        assert "plan" in all_system_text or "step" in all_system_text, (
            "Agent must inject a planning prompt for complex multi-step tasks"
        )


# ---------------------------------------------------------------------------
# Golden 10: Parallel readonly tools — multiple reads in one iteration
# ---------------------------------------------------------------------------


class TestGoldenParallelReadonlyTools:
    """When the LLM requests multiple readonly tools simultaneously,
    the agent must execute them all and include all results in the next call.
    """

    @pytest.mark.asyncio
    async def test_multiple_read_results_in_context(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("alpha")
        (tmp_path / "b.txt").write_text("beta")

        provider = ScriptedProvider(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="tc1",
                            name="read_file",
                            arguments={"path": str(tmp_path / "a.txt")},
                        ),
                        ToolCallRequest(
                            id="tc2",
                            name="read_file",
                            arguments={"path": str(tmp_path / "b.txt")},
                        ),
                    ],
                ),
                LLMResponse(content="Both files read."),
            ]
        )
        loop = _make_loop(tmp_path, provider)
        result = await loop._process_message(_make_inbound("read both"))

        assert result is not None
        assert len(provider.call_log) == 2

        # The second call must have tool results for BOTH files
        second_tool_results = _tool_result_messages(provider.call_log[1]["messages"])
        result_text = " ".join(tr["content"] for tr in second_tool_results)
        assert "alpha" in result_text, "First parallel tool result missing"
        assert "beta" in result_text, "Second parallel tool result missing"
