"""Tests for the structured agent workflow."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.runner import AgentRunResult, AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.workflow import (
    WorkflowContext,
    WorkflowResult,
    WorkflowRunner,
    is_workflow_enabled,
    run_with_workflow_fallback,
)
from nanobot.providers.base import LLMResponse, ToolCallRequest


class DummyProvider(MagicMock):
    """A mock provider for testing."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        super().__init__()
        self._responses = list(responses) if responses else []
        self._call_count = 0

    def get_default_model(self) -> str:
        return "test-model"


def _tool_call_response(
    tool_name: str, arguments: dict, content: str = ""
) -> LLMResponse:
    """Create an LLMResponse that calls a tool."""
    return LLMResponse(
        content=content,
        tool_calls=[
            ToolCallRequest(
                id=f"call_{tool_name}", name=tool_name, arguments=arguments
            )
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )


def _text_response(content: str) -> LLMResponse:
    """Create a simple text LLMResponse."""
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )


class TestWorkflowEnabledCheck:
    """Tests for is_workflow_enabled function."""

    def test_default_disabled(self):
        """Workflow should be disabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_workflow_enabled() is False

    def test_enabled_with_1(self):
        """Workflow enabled with NANOBOT_AGENT_WORKFLOW=1."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "1"}):
            assert is_workflow_enabled() is True

    def test_enabled_with_true(self):
        """Workflow enabled with NANOBOT_AGENT_WORKFLOW=true."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "true"}):
            assert is_workflow_enabled() is True

    def test_enabled_with_yes(self):
        """Workflow enabled with NANOBOT_AGENT_WORKFLOW=yes."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "yes"}):
            assert is_workflow_enabled() is True

    def test_enabled_with_on(self):
        """Workflow enabled with NANOBOT_AGENT_WORKFLOW=on."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "on"}):
            assert is_workflow_enabled() is True

    def test_disabled_with_0(self):
        """Workflow disabled with NANOBOT_AGENT_WORKFLOW=0."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "0"}):
            assert is_workflow_enabled() is False

    def test_disabled_with_false(self):
        """Workflow disabled with NANOBOT_AGENT_WORKFLOW=false."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "false"}):
            assert is_workflow_enabled() is False

    def test_case_insensitive(self):
        """Environment variable check should be case-insensitive."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "TRUE"}):
            assert is_workflow_enabled() is True
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "True"}):
            assert is_workflow_enabled() is True


class TestWorkflowContext:
    """Tests for WorkflowContext dataclass."""

    def test_initialization(self):
        """Context should initialize with default values."""
        ctx = WorkflowContext(
            original_messages=[{"role": "user", "content": "test"}],
            task_description="test task",
            tools=ToolRegistry(),
            model="test-model",
            provider=MagicMock(),
        )
        assert ctx.task_type == "unknown"
        assert ctx.task_complexity == "unknown"
        assert ctx.plan_steps == []
        assert ctx.execution_messages == []
        assert ctx.final_content is None
        assert ctx.tools_used == []
        assert ctx.stop_reason == "workflow_pending"
        assert ctx.validation_passed is False
        assert ctx.compressed_summary == ""
        assert ctx.final_report == ""


class TestWorkflowRunner:
    """Tests for WorkflowRunner class."""

    @pytest.mark.asyncio
    async def test_classify_task_success(self):
        """Task classification should work when tool call is returned."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_tool_call_response(
                "classify_task",
                {
                    "task_type": "coding",
                    "complexity": "medium",
                    "requires_plan": True,
                    "reasoning": "Test task involves code modification",
                },
            )
        )

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[{"role": "user", "content": "fix the bug"}],
            task_description="fix the bug",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )

        result = await runner._classify_task(ctx)
        assert result is True
        assert ctx.task_type == "coding"
        assert ctx.task_complexity == "medium"

    @pytest.mark.asyncio
    async def test_classify_task_no_tool_call(self):
        """Classification should return False when no tool call is returned."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=_text_response("I think this is a coding task."))

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[{"role": "user", "content": "test"}],
            task_description="test",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )

        result = await runner._classify_task(ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_classify_task_exception(self):
        """Classification should handle exceptions gracefully."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("API down"))

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[{"role": "user", "content": "test"}],
            task_description="test",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )

        result = await runner._classify_task(ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_create_plan_simple_query(self):
        """Simple queries should skip planning."""
        provider = MagicMock()
        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="what time is it?",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "simple_query"
        ctx.task_complexity = "simple"

        result = await runner._create_plan(ctx)
        assert result is True
        assert len(ctx.plan_steps) == 1
        assert "directly" in ctx.plan_steps[0].get("description", "").lower()

    @pytest.mark.asyncio
    async def test_create_plan_with_tool_call(self):
        """Planning should work when tool call is returned."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_tool_call_response(
                "create_plan",
                {
                    "steps": [
                        {"description": "Read the file", "tools": ["read_file"]},
                        {"description": "Analyze and fix", "tools": ["edit_file"]},
                    ],
                    "expected_duration": "5 minutes",
                    "success_criteria": ["Bug is fixed", "Tests pass"],
                },
            )
        )

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="fix bug",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "coding"
        ctx.task_complexity = "medium"

        result = await runner._create_plan(ctx)
        assert result is True
        assert len(ctx.plan_steps) == 2
        assert ctx.plan_steps[0]["description"] == "Read the file"

    @pytest.mark.asyncio
    async def test_create_plan_no_tool_call(self):
        """Planning should return False when no tool call."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=_text_response("Here's my plan..."))

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="fix bug",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "coding"
        ctx.task_complexity = "medium"

        result = await runner._create_plan(ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_compress_results_short_message(self):
        """Compression should be skipped if message count is low."""
        provider = MagicMock()
        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[{"role": "user", "content": "test"}],
            task_description="test",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.execution_messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        ctx.final_content = "The answer is 42"

        result = await runner._compress_results(ctx)
        assert result is True
        assert ctx.compressed_summary == "The answer is 42"

    @pytest.mark.asyncio
    async def test_compress_results_with_llm(self):
        """Compression should use LLM when there are many messages."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=_text_response("Compressed: The task involved reading files and making changes."))

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[{"role": "user", "content": "test"}],
            task_description="test",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.execution_messages = [
            {"role": f"role_{i}", "content": f"message_{i}"}
            for i in range(15)
        ]
        ctx.final_content = "Long detailed response..."

        result = await runner._compress_results(ctx)
        assert result is True
        assert "Compressed" in ctx.compressed_summary

    @pytest.mark.asyncio
    async def test_validate_result_simple_query(self):
        """Validation should be skipped for simple queries."""
        provider = MagicMock()
        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="hello",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "simple_query"

        result = await runner._validate_result(ctx)
        assert result is True
        assert ctx.validation_passed is True
        assert "simple" in ctx.validation_reason.lower()

    @pytest.mark.asyncio
    async def test_validate_result_with_tool_call(self):
        """Validation should work when tool call is returned."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_tool_call_response(
                "validate_result",
                {
                    "passed": True,
                    "reason": "All requirements met",
                    "missing_items": [],
                },
            )
        )

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="fix bug",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "coding"
        ctx.compressed_summary = "Fixed the bug"

        result = await runner._validate_result(ctx)
        assert result is True
        assert ctx.validation_passed is True

    @pytest.mark.asyncio
    async def test_validate_result_no_tool_call_fallback(self):
        """Validation should fall back to passed=True when no tool call."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=_text_response("Looks good!"))

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="fix bug",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "coding"

        result = await runner._validate_result(ctx)
        assert result is True
        assert ctx.validation_passed is True

    @pytest.mark.asyncio
    async def test_generate_report_simple_task(self):
        """Report generation should be skipped for simple tasks."""
        provider = MagicMock()
        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="hi",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "simple_query"
        ctx.task_complexity = "simple"
        ctx.compressed_summary = "Hello!"

        result = await runner._generate_report(ctx)
        assert result is True
        assert ctx.final_report == "Hello!"

    @pytest.mark.asyncio
    async def test_generate_report_with_llm(self):
        """Report generation should use LLM for complex tasks."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=_text_response("# Task Report\n\nSuccessfully completed the coding task."))

        runner = WorkflowRunner(provider)
        ctx = WorkflowContext(
            original_messages=[],
            task_description="implement feature",
            tools=ToolRegistry(),
            model="test-model",
            provider=provider,
        )
        ctx.task_type = "coding"
        ctx.task_complexity = "complex"
        ctx.compressed_summary = "Done"
        ctx.tools_used = ["read_file", "edit_file"]
        ctx.validation_passed = True
        ctx.validation_reason = "All tests pass"

        result = await runner._generate_report(ctx)
        assert result is True
        assert "Task Report" in ctx.final_report


class TestRunWithWorkflowFallback:
    """Tests for the main entry point with fallback."""

    @pytest.mark.asyncio
    async def test_workflow_disabled_uses_traditional(self):
        """When workflow is disabled, should use traditional runner directly."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=_text_response("done"))

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "hi"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=1000,
        )

        with patch.dict(os.environ, {}, clear=True):
            result = await run_with_workflow_fallback(spec, provider)

        assert result.final_content == "done"

    @pytest.mark.asyncio
    async def test_workflow_enabled_but_fails_fallback(self):
        """When workflow is enabled but fails, should fall back to traditional."""
        call_count = {"n": 0}

        async def chat_with_retry(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Classification failed")
            return _text_response("fallback answer")

        provider = MagicMock()
        provider.chat_with_retry = chat_with_retry

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "hi"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=1000,
        )

        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "1"}):
            result = await run_with_workflow_fallback(spec, provider)

        assert result.final_content == "fallback answer"

    @pytest.mark.asyncio
    async def test_no_initial_messages_fallback(self):
        """Workflow should fall back when no initial messages."""
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(return_value=_text_response("ok"))

        spec = AgentRunSpec(
            initial_messages=[],
            tools=MagicMock(),
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=1000,
        )

        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "1"}):
            result = await run_with_workflow_fallback(spec, provider)

        assert result is not None


class TestWorkflowIntegration:
    """Integration tests for the full workflow pipeline."""

    @pytest.mark.asyncio
    async def test_full_workflow_success(self):
        """Full workflow should succeed when all phases work."""
        call_count = {"n": 0}
        responses = [
            _tool_call_response(
                "classify_task",
                {
                    "task_type": "coding",
                    "complexity": "medium",
                    "requires_plan": True,
                    "reasoning": "Coding task",
                },
            ),
            _tool_call_response(
                "create_plan",
                {
                    "steps": [{"description": "Read file"}],
                    "expected_duration": "1 min",
                    "success_criteria": ["File read"],
                },
            ),
            _text_response("Execution result"),
            _text_response("Compressed result"),
            _tool_call_response(
                "validate_result",
                {"passed": True, "reason": "All good", "missing_items": []},
            ),
            _text_response("Final report"),
        ]

        async def chat_with_retry(**kwargs):
            nonlocal call_count
            if call_count["n"] < len(responses):
                resp = responses[call_count["n"]]
                call_count["n"] += 1
                return resp
            return _text_response("done")

        provider = MagicMock()
        provider.chat_with_retry = chat_with_retry

        tools = MagicMock()
        tools.get_definitions.return_value = []
        tools.execute = AsyncMock(return_value="tool result")
        tools.tool_names = ["read_file"]

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "read test.txt"}],
            tools=tools,
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=1000,
        )

        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "1"}):
            with patch("nanobot.agent.workflow.WorkflowRunner._execute_plan") as mock_exec:
                mock_exec.return_value = AgentRunResult(
                    final_content="Execution result",
                    messages=[{"role": "assistant", "content": "done"}],
                    tools_used=["read_file"],
                    usage={},
                    stop_reason="completed",
                )
                result = await run_with_workflow_fallback(spec, provider)

        assert result is not None
        assert result.stop_reason == "completed"
