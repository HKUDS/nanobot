"""Tests for the AgentWorkflow structured task processing pipeline.

This module tests:
1. is_workflow_enabled() environment variable switch
2. RestrictedToolRegistry - TRUE CLOSED-LOOP tool restriction
3. AgentWorkflow 6-phase pipeline with TRUE CLOSED-LOOP behavior:
   - Classification ACTUALLY determines tool availability
   - Plan ACTUALLY guides each execution step
4. Fallback mechanism when workflow phases fail
5. Integration with existing AgentRunner
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.runner import AgentRunResult, AgentRunSpec, AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.workflow import (
    AgentWorkflow,
    RestrictedToolRegistry,
    StepExecutionResult,
    WorkflowResult,
    _CLASSIFY_TOOL,
    _COMPRESS_TOOL,
    _PLAN_TOOL,
    _REPORT_TOOL,
    _STEP_VALIDATION_TOOL,
    _VALIDATE_TOOL,
    is_workflow_enabled,
)
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


class TestIsWorkflowEnabled:
    """Tests for the is_workflow_enabled() function."""

    def test_disabled_by_default(self):
        """Workflow should be disabled when environment variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_workflow_enabled() is False

    def test_enabled_with_1(self):
        """Workflow should be enabled with NANOBOT_AGENT_WORKFLOW=1."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "1"}):
            assert is_workflow_enabled() is True

    def test_enabled_with_true(self):
        """Workflow should be enabled with NANOBOT_AGENT_WORKFLOW=true."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "true"}):
            assert is_workflow_enabled() is True

    def test_enabled_with_yes(self):
        """Workflow should be enabled with NANOBOT_AGENT_WORKFLOW=yes."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "yes"}):
            assert is_workflow_enabled() is True

    def test_enabled_with_on(self):
        """Workflow should be enabled with NANOBOT_AGENT_WORKFLOW=on."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "on"}):
            assert is_workflow_enabled() is True

    def test_case_insensitive(self):
        """Environment variable value should be case-insensitive."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "TRUE"}):
            assert is_workflow_enabled() is True

        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "Yes"}):
            assert is_workflow_enabled() is True

    def test_disabled_with_0(self):
        """Workflow should be disabled with NANOBOT_AGENT_WORKFLOW=0."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "0"}):
            assert is_workflow_enabled() is False

    def test_disabled_with_false(self):
        """Workflow should be disabled with NANOBOT_AGENT_WORKFLOW=false."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "false"}):
            assert is_workflow_enabled() is False

    def test_strips_whitespace(self):
        """Environment variable value should have whitespace stripped."""
        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "  1  "}):
            assert is_workflow_enabled() is True

        with patch.dict(os.environ, {"NANOBOT_AGENT_WORKFLOW": "  0  "}):
            assert is_workflow_enabled() is False


class TestRestrictedToolRegistry:
    """Tests for the RestrictedToolRegistry class - TRUE CLOSED-LOOP core.

    This is the KEY component that enables TRUE CLOSED-LOOP behavior:
    - Classification can disable all tools (simple_qa)
    - Classification can restrict to recommended tools
    - Classification can block specific tools
    - Plan steps can further restrict tools
    """

    @pytest.fixture
    def mock_tool_a(self):
        """Create a mock tool."""
        tool = MagicMock()
        tool.name = "read_file"
        tool.description = "Read file contents"
        tool.to_schema.return_value = {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file contents",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        return tool

    @pytest.fixture
    def mock_tool_b(self):
        """Create another mock tool."""
        tool = MagicMock()
        tool.name = "write_file"
        tool.description = "Write file contents"
        tool.to_schema.return_value = {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write file contents",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        return tool

    @pytest.fixture
    def mock_tool_c(self):
        """Create a third mock tool."""
        tool = MagicMock()
        tool.name = "exec"
        tool.description = "Execute commands"
        tool.to_schema.return_value = {
            "type": "function",
            "function": {
                "name": "exec",
                "description": "Execute commands",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        return tool

    @pytest.fixture
    def original_registry(self, mock_tool_a, mock_tool_b, mock_tool_c):
        """Create an original registry with multiple tools."""
        registry = ToolRegistry()
        registry.register(mock_tool_a)
        registry.register(mock_tool_b)
        registry.register(mock_tool_c)
        return registry

    def test_no_restrictions_uses_all_tools(self, original_registry, mock_tool_a, mock_tool_b, mock_tool_c):
        """When no restrictions are set, all tools should be available."""
        restricted = RestrictedToolRegistry(original=original_registry)

        assert restricted.has("read_file") is True
        assert restricted.has("write_file") is True
        assert restricted.has("exec") is True
        assert len(restricted) == 3
        assert set(restricted.tool_names) == {"read_file", "write_file", "exec"}

    def test_allowed_tools_restricts_availability(self, original_registry, mock_tool_a, mock_tool_b, mock_tool_c):
        """When allowed_tools is set, only those tools should be available.

        This is used for:
        - classification.recommended_tools
        - step.tools_allowed
        """
        restricted = RestrictedToolRegistry(
            original=original_registry,
            allowed_tools=["read_file", "write_file"],
        )

        assert restricted.has("read_file") is True
        assert restricted.has("write_file") is True
        assert restricted.has("exec") is False
        assert len(restricted) == 2
        assert set(restricted.tool_names) == {"read_file", "write_file"}

    def test_blocked_tools_disables_specific_tools(self, original_registry, mock_tool_a, mock_tool_b, mock_tool_c):
        """When blocked_tools is set, those tools should be unavailable.

        This is used for:
        - classification.blocked_tools
        - plan.overall_tool_restrictions
        """
        restricted = RestrictedToolRegistry(
            original=original_registry,
            blocked_tools=["exec"],
        )

        assert restricted.has("read_file") is True
        assert restricted.has("write_file") is True
        assert restricted.has("exec") is False
        assert len(restricted) == 2

    def test_allowed_and_blocked_together(self, original_registry, mock_tool_a, mock_tool_b, mock_tool_c):
        """blocked_tools takes precedence over allowed_tools."""
        restricted = RestrictedToolRegistry(
            original=original_registry,
            allowed_tools=["read_file", "write_file", "exec"],
            blocked_tools=["exec"],
        )

        assert restricted.has("read_file") is True
        assert restricted.has("write_file") is True
        assert restricted.has("exec") is False
        assert len(restricted) == 2

    def test_needs_tools_false_disables_all_tools(self, original_registry, mock_tool_a, mock_tool_b, mock_tool_c):
        """When classification.needs_tools=False, ALL tools are blocked.

        This is the KEY TRUE CLOSED-LOOP behavior for simple_qa tasks:
        - If the task doesn't need tools, tools are HARD BLOCKED
        - The agent CANNOT call any tools
        """
        all_tool_names = list(original_registry.tool_names)

        restricted = RestrictedToolRegistry(
            original=original_registry,
            blocked_tools=all_tool_names,
        )

        assert restricted.has("read_file") is False
        assert restricted.has("write_file") is False
        assert restricted.has("exec") is False
        assert len(restricted) == 0
        assert restricted.tool_names == []

    def test_get_disallowed_tool_returns_none(self, original_registry):
        """get() should return None for disallowed tools."""
        restricted = RestrictedToolRegistry(
            original=original_registry,
            allowed_tools=["read_file"],
        )

        assert restricted.get("read_file") is not None
        assert restricted.get("write_file") is None
        assert restricted.get("exec") is None

    def test_get_definitions_only_includes_allowed_tools(self, original_registry):
        """get_definitions() should only return schemas for allowed tools."""
        restricted = RestrictedToolRegistry(
            original=original_registry,
            allowed_tools=["read_file", "write_file"],
        )

        definitions = restricted.get_definitions()
        names = [ToolRegistry._schema_name(d) for d in definitions]

        assert "read_file" in names
        assert "write_file" in names
        assert "exec" not in names
        assert len(definitions) == 2

    def test_prepare_call_disallowed_tool_returns_error(self, original_registry):
        """prepare_call() should return an error for disallowed tools."""
        restricted = RestrictedToolRegistry(
            original=original_registry,
            allowed_tools=["read_file"],
        )

        tool, params, error = restricted.prepare_call("write_file", {"path": "test.txt"})

        assert tool is None
        assert error is not None
        assert "not available" in error or "not allowed" in error

    def test_in_operator_works_correctly(self, original_registry):
        """'in' operator should work correctly with restrictions."""
        restricted = RestrictedToolRegistry(
            original=original_registry,
            allowed_tools=["read_file", "write_file"],
        )

        assert "read_file" in restricted
        assert "write_file" in restricted
        assert "exec" not in restricted


class TestAgentWorkflowHelpers:
    """Tests for AgentWorkflow helper methods."""

    @pytest.fixture
    def mock_provider(self):
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        return provider

    @pytest.fixture
    def workflow(self, mock_provider):
        async def legacy_fn():
            return AgentRunResult(
                final_content="done",
                messages=[],
                stop_reason="completed",
            )

        return AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

    def test_extract_user_request_from_string(self, workflow):
        """Should extract user request from string content."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm fine, thanks!"},
            {"role": "user", "content": "What's the weather?"},
        ]

        result = workflow._extract_user_request(messages)
        assert result == "What's the weather?"

    def test_extract_user_request_from_blocks(self, workflow):
        """Should extract user request from multimodal content blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this image"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
                    {"type": "text", "text": " and tell me what you see."},
                ],
            },
        ]

        result = workflow._extract_user_request(messages)
        assert "Look at this image" in result
        assert "tell me what you see" in result

    def test_extract_user_request_no_user_message(self, workflow):
        """Should return empty string when no user message exists."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "assistant", "content": "I'm an assistant"},
        ]

        result = workflow._extract_user_request(messages)
        assert result == ""

    def test_extract_context_summary(self, workflow):
        """Should extract a summary of the conversation context."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello! How can I help you today?"},
            {"role": "user", "content": "What's 2 + 2?"},
            {"role": "assistant", "content": "2 + 2 = 4"},
            {"role": "tool", "tool_call_id": "call_1", "name": "list_dir", "content": "file1.txt"},
        ]

        result = workflow._extract_context_summary(messages)
        assert "System prompt" in result
        assert "Assistant" in result
        assert "Tool: list_dir" in result

    def test_messages_to_text(self, workflow):
        """Should convert message list to readable text format."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": "Thinking...",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "list_dir", "content": "file1.txt\nfile2.txt"},
            {"role": "assistant", "content": "Done!"},
        ]

        result = workflow._messages_to_text(messages)
        assert "## System" in result
        assert "## User" in result
        assert "## Assistant" in result
        assert "Tool calls: list_dir" in result
        assert "## Tool Result (list_dir" in result

    def test_build_step_context_injection(self, workflow):
        """Should build proper step context injection with classification and plan info.

        This is part of the TRUE CLOSED-LOOP: plan guidance is ACTUALLY injected.
        """
        step = {
            "step_number": 1,
            "description": "Read the config file",
            "execution_guidance": "Look for the database connection string",
            "expected_outcome": "We have the database URL",
            "tools_allowed": ["read_file", "grep"],
            "tools_preferred": ["read_file"],
            "tools_avoid": ["write_file"],
            "validation_query": "Did we find the database connection string?",
        }

        overall_plan = {
            "overall_goal": "Connect to the database and fetch data",
            "steps": [step],
        }

        classification = {
            "primary_category": "information_gathering",
            "estimated_complexity": "medium",
            "needs_tools": True,
            "recommended_tools": ["read_file", "grep"],
            "blocked_tools": ["exec"],
        }

        result = workflow._build_step_context_injection(step, overall_plan, classification)

        assert "WORKFLOW GUIDANCE" in result
        assert "information_gathering" in result
        assert "medium" in result
        assert "read_file" in result
        assert "grep" in result
        assert "exec" in result
        assert "Step 1 of 1" in result
        assert "Look for the database connection string" in result
        assert "Did we find the database connection string?" in result

    def test_inject_step_guidance_appends_to_last_user_message(self, workflow):
        """Should append step guidance to the last user message."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Read the config file"},
        ]

        step_context = "--- WORKFLOW GUIDANCE ---\nUse read_file tool\n---"

        result = workflow._inject_step_guidance(messages, step_context)

        assert len(result) == 2
        assert "Read the config file" in result[1]["content"]
        assert "WORKFLOW GUIDANCE" in result[1]["content"]

    def test_create_restricted_tools_with_needs_tools_false(self, workflow):
        """When needs_tools=False, all tools should be blocked.

        This is TRUE CLOSED-LOOP: classification ACTUALLY disables tools.
        """
        original_registry = MagicMock(spec=ToolRegistry)
        original_registry.tool_names = ["read_file", "write_file", "exec"]

        classification = {
            "primary_category": "simple_qa",
            "needs_tools": False,
        }

        with patch("nanobot.agent.workflow.RestrictedToolRegistry") as mock_restricted:
            workflow._create_restricted_tools(original_registry, classification)

            mock_restricted.assert_called_once()
            call_args = mock_restricted.call_args

            assert call_args.kwargs["original"] is original_registry
            blocked = call_args.kwargs.get("blocked_tools")
            assert blocked == ["read_file", "write_file", "exec"]

    def test_build_report_content(self, workflow):
        """Should convert report dict to user-facing string."""
        report = {
            "summary": "I've successfully completed the task of creating a Python script.",
            "final_status": "success",
            "confidence": 9,
            "actions_taken": ["Created script.py", "Added main function"],
            "key_results": ["Script runs successfully"],
            "files_modified": ["script.py: New Python script"],
            "issues_encountered": [],
            "next_steps": ["Test the script"],
            "user_questions": [],
        }

        result = workflow._build_report_content(report)

        assert "successfully completed" in result
        assert "✅ Status: Success" in result
        assert "Confidence: 9/10" in result
        assert "## Actions Taken" in result
        assert "Created script.py" in result
        assert "## Key Results" in result
        assert "## Files Modified" in result
        assert "## Next Steps" in result

    def test_build_report_content_with_issues(self, workflow):
        """Should include issues encountered when present."""
        report = {
            "summary": "Task partially completed.",
            "final_status": "partial_success",
            "confidence": 6,
            "issues_encountered": ["Network error when fetching data"],
            "user_questions": ["Should I use a different API?"],
        }

        result = workflow._build_report_content(report)

        assert "⚠️ Status: Partial Success" in result
        assert "## Issues Encountered" in result
        assert "Network error" in result
        assert "## Questions for You" in result
        assert "Should I use a different API?" in result

    def test_build_report_content_with_failure(self, workflow):
        """Should show failure status correctly."""
        report = {
            "summary": "Task failed due to permission errors.",
            "final_status": "failed",
            "confidence": 3,
        }

        result = workflow._build_report_content(report)

        assert "❌ Status: Failed" in result


class TestAgentWorkflowExecution:
    """Tests for AgentWorkflow execution phases."""

    @pytest.fixture
    def mock_provider(self):
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        return provider

    @pytest.fixture
    def legacy_result(self):
        return AgentRunResult(
            final_content="The script has been created successfully.",
            messages=[
                {"role": "user", "content": "Create a Python script"},
                {"role": "assistant", "content": "I'll create a script for you.", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "write_file"}}]},
                {"role": "tool", "tool_call_id": "call_1", "name": "write_file", "content": "File created"},
                {"role": "assistant", "content": "The script has been created successfully."},
            ],
            tools_used=["write_file"],
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            stop_reason="completed",
            tool_events=[{"name": "write_file", "status": "ok", "detail": "File created"}],
            had_injections=False,
        )

    @pytest.mark.asyncio
    async def test_classify_phase(self, mock_provider, legacy_result):
        """Test the task classification phase with enhanced fields."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="classify_1",
                name="classify_task",
                arguments={
                    "primary_category": "code_modification",
                    "secondary_categories": ["file_management"],
                    "reasoning": "User wants to create a Python script, which involves writing code.",
                    "estimated_complexity": "low",
                    "needs_tools": True,
                    "recommended_tools": ["write_file", "read_file"],
                    "blocked_tools": ["exec"],
                    "suggested_max_iterations": 3,
                },
            )],
            usage={"prompt_tokens": 50, "completion_tokens": 20},
        ))

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Create a Python script that prints 'Hello World'"},
        ]

        result = await workflow._classify(messages)

        assert result is not None
        assert result["primary_category"] == "code_modification"
        assert result["estimated_complexity"] == "low"
        assert result["needs_tools"] is True
        assert result["recommended_tools"] == ["write_file", "read_file"]
        assert result["blocked_tools"] == ["exec"]
        assert result["suggested_max_iterations"] == 3

        mock_provider.chat_with_retry.assert_awaited_once()
        call_kwargs = mock_provider.chat_with_retry.await_args.kwargs
        assert call_kwargs["tools"] == _CLASSIFY_TOOL
        assert call_kwargs["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_classify_phase_returns_none_on_error(self, mock_provider, legacy_result):
        """Test that classification returns None when LLM call fails."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(side_effect=Exception("LLM API error"))

        messages = [
            {"role": "user", "content": "Create a Python script"},
        ]

        result = await workflow._classify(messages)

        assert result is None

    @pytest.mark.asyncio
    async def test_classify_phase_returns_none_when_no_tool_call(self, mock_provider, legacy_result):
        """Test that classification returns None when no tool call is returned."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="I think this is a code modification task.",
            tool_calls=[],
            usage={"prompt_tokens": 50, "completion_tokens": 20},
        ))

        messages = [
            {"role": "user", "content": "Create a Python script"},
        ]

        result = await workflow._classify(messages)

        assert result is None

    @pytest.mark.asyncio
    async def test_plan_phase(self, mock_provider, legacy_result):
        """Test the planning phase with enhanced step fields.

        These fields are used in TRUE CLOSED-LOOP execution:
        - execution_guidance: injected into context
        - tools_allowed: restricts available tools
        - validation_query: used to verify step completion
        """
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="plan_1",
                name="create_plan",
                arguments={
                    "overall_goal": "Create a Python script that prints 'Hello World'",
                    "steps": [
                        {
                            "step_number": 1,
                            "description": "Create the Python script file",
                            "execution_guidance": "Use write_file to create hello.py with print('Hello World')",
                            "tools_allowed": ["write_file"],
                            "tools_preferred": ["write_file"],
                            "tools_avoid": ["exec"],
                            "expected_outcome": "A file named hello.py exists with correct content",
                            "validation_query": "Is hello.py created with the correct content?",
                        },
                    ],
                    "estimated_iterations": 1,
                    "potential_risks": ["Permission denied when writing file"],
                    "success_criteria": "File is created and contains 'print(\"Hello World\")'",
                },
            )],
            usage={"prompt_tokens": 80, "completion_tokens": 50},
        ))

        classification = {
            "primary_category": "code_modification",
            "estimated_complexity": "low",
            "needs_tools": True,
        }

        messages = [
            {"role": "user", "content": "Create a Python script"},
        ]

        result = await workflow._plan(messages, classification)

        assert result is not None
        assert result["overall_goal"] == "Create a Python script that prints 'Hello World'"
        assert len(result["steps"]) == 1

        step = result["steps"][0]
        assert step["step_number"] == 1
        assert step["execution_guidance"] is not None
        assert step["tools_allowed"] == ["write_file"]
        assert step["validation_query"] is not None

        mock_provider.chat_with_retry.assert_awaited_once()
        call_kwargs = mock_provider.chat_with_retry.await_args.kwargs
        assert call_kwargs["tools"] == _PLAN_TOOL

    @pytest.mark.asyncio
    async def test_validate_step_phase(self, mock_provider, legacy_result):
        """Test the step validation phase.

        This is part of TRUE CLOSED-LOOP: each step is validated after execution.
        """
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="validate_step_1",
                name="validate_step",
                arguments={
                    "step_complete": True,
                    "confidence": 9,
                    "reasoning": "The file was created successfully and contains the expected content.",
                    "next_action": "proceed",
                    "adjustments_needed": None,
                },
            )],
            usage={"prompt_tokens": 50, "completion_tokens": 30},
        ))

        step = {
            "step_number": 1,
            "description": "Create hello.py",
            "expected_outcome": "File exists",
            "validation_query": "Is hello.py created?",
        }

        execution_messages = [
            {"role": "user", "content": "Create hello.py"},
            {"role": "assistant", "content": "Creating...", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "write_file"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "write_file", "content": "File created"},
            {"role": "assistant", "content": "Done!"},
        ]

        result = await workflow._validate_step(step, execution_messages)

        assert result is not None
        assert result["step_complete"] is True
        assert result["confidence"] == 9
        assert result["next_action"] == "proceed"

        mock_provider.chat_with_retry.assert_awaited_once()
        call_kwargs = mock_provider.chat_with_retry.await_args.kwargs
        assert call_kwargs["tools"] == _STEP_VALIDATION_TOOL

    @pytest.mark.asyncio
    async def test_compress_phase(self, mock_provider, legacy_result):
        """Test the compression phase."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="compress_1",
                name="compress_conversation",
                arguments={
                    "original_task": "Create a Python script",
                    "key_decisions": ["Use write_file tool to create the script"],
                    "tools_used_summary": ["write_file: Created hello.py"],
                    "files_modified": ["hello.py: New Python script"],
                    "errors_encountered": [],
                    "current_state": "Script created successfully",
                    "remaining_questions": [],
                    "key_insights": ["Simple tasks require only one tool call"],
                },
            )],
            usage={"prompt_tokens": 100, "completion_tokens": 60},
        ))

        result = await workflow._compress(
            original_task="Create a Python script",
            plan={"overall_goal": "Create script", "steps": []},
            execution_result=legacy_result,
        )

        assert result is not None
        assert result["original_task"] == "Create a Python script"
        assert result["current_state"] == "Script created successfully"

        mock_provider.chat_with_retry.assert_awaited_once()
        call_kwargs = mock_provider.chat_with_retry.await_args.kwargs
        assert call_kwargs["tools"] == _COMPRESS_TOOL

    @pytest.mark.asyncio
    async def test_validate_phase(self, mock_provider, legacy_result):
        """Test the validation phase."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="validate_1",
                name="validate_execution",
                arguments={
                    "task_understood": True,
                    "success_criteria_met": True,
                    "steps_completed": ["Created script file"],
                    "steps_incomplete": [],
                    "errors_found": [],
                    "files_verified": ["hello.py exists and has correct content"],
                    "validation_summary": "Task completed successfully.",
                    "confidence_score": 9,
                    "recommendations": ["Test the script"],
                    "needs_user_input": False,
                },
            )],
            usage={"prompt_tokens": 80, "completion_tokens": 40},
        ))

        result = await workflow._validate(
            original_task="Create a Python script",
            plan={"overall_goal": "Create script", "steps": [], "success_criteria": "File exists"},
            compressed={"original_task": "Create script", "current_state": "Done"},
            execution_result=legacy_result,
        )

        assert result is not None
        assert result["task_understood"] is True
        assert result["success_criteria_met"] is True
        assert result["confidence_score"] == 9

        mock_provider.chat_with_retry.assert_awaited_once()
        call_kwargs = mock_provider.chat_with_retry.await_args.kwargs
        assert call_kwargs["tools"] == _VALIDATE_TOOL

    @pytest.mark.asyncio
    async def test_report_phase(self, mock_provider, legacy_result):
        """Test the reporting phase."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="report_1",
                name="generate_report",
                arguments={
                    "summary": "I've successfully created a Python script that prints 'Hello World'.",
                    "actions_taken": ["Created hello.py with print('Hello World')"],
                    "key_results": ["Script file created successfully"],
                    "files_modified": ["hello.py: New Python script"],
                    "issues_encountered": [],
                    "next_steps": ["Run the script to verify it works"],
                    "user_questions": [],
                    "final_status": "success",
                    "confidence": 9,
                },
            )],
            usage={"prompt_tokens": 100, "completion_tokens": 80},
        ))

        result = await workflow._report(
            original_task="Create a Python script",
            plan={"overall_goal": "Create script", "steps": []},
            validation={
                "task_understood": True,
                "success_criteria_met": True,
                "validation_summary": "Task completed",
                "confidence_score": 9,
            },
            compressed={"original_task": "Create script", "current_state": "Done"},
        )

        assert result is not None
        assert result["final_status"] == "success"
        assert result["confidence"] == 9
        assert "successfully created" in result["summary"]

        mock_provider.chat_with_retry.assert_awaited_once()
        call_kwargs = mock_provider.chat_with_retry.await_args.kwargs
        assert call_kwargs["tools"] == _REPORT_TOOL


class TestAgentWorkflowFallback:
    """Tests for the workflow fallback mechanism."""

    @pytest.fixture
    def mock_provider(self):
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        return provider

    @pytest.fixture
    def legacy_result(self):
        return AgentRunResult(
            final_content="Legacy execution result.",
            messages=[{"role": "user", "content": "Test"}, {"role": "assistant", "content": "Legacy execution result."}],
            tools_used=[],
            usage={"prompt_tokens": 50, "completion_tokens": 30},
            stop_reason="completed",
        )

    @pytest.mark.asyncio
    async def test_fallback_when_classification_fails(self, mock_provider, legacy_result):
        """Should fall back to legacy when classification fails."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="I can't classify this task without more info.",
            tool_calls=[],
        ))

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Create a Python script"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        result = await workflow.run(spec)

        assert result.fallback_used is True
        assert result.fallback_reason == "classification_failed"
        assert result.execution_result is legacy_result
        assert result.classification is None

    @pytest.mark.asyncio
    async def test_fallback_when_planning_fails(self, mock_provider, legacy_result):
        """Should fall back to legacy when planning fails."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        classification_response = LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="classify_1",
                name="classify_task",
                arguments={
                    "primary_category": "code_modification",
                    "reasoning": "User wants to create code",
                    "estimated_complexity": "low",
                    "needs_tools": True,
                },
            )],
        )

        mock_provider.chat_with_retry = AsyncMock(side_effect=[
            classification_response,
            Exception("Planning LLM call failed"),
        ])

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Create a Python script"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        result = await workflow.run(spec)

        assert result.fallback_used is True
        assert "planning_failed" in (result.fallback_reason or "")
        assert result.execution_result is legacy_result
        assert result.classification is not None
        assert result.plan is None

    @pytest.mark.asyncio
    async def test_fallback_when_classification_llm_fails(self, mock_provider, legacy_result):
        """Should fall back to legacy when classification phase LLM call fails."""
        async def legacy_fn():
            return legacy_result

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(side_effect=Exception("LLM API error"))

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Test"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        result = await workflow.run(spec)

        assert result.fallback_used is True
        assert result.fallback_reason == "classification_failed"
        assert result.execution_result is legacy_result
        assert result.classification is None

    @pytest.mark.asyncio
    async def test_fallback_when_legacy_and_workflow_both_fail(self, mock_provider):
        """Should handle both workflow and legacy failing gracefully."""
        async def legacy_fn():
            raise Exception("Legacy execution also failed")

        workflow = AgentWorkflow(
            provider=mock_provider,
            model="test-model",
            run_legacy_fn=legacy_fn,
        )

        mock_provider.chat_with_retry = AsyncMock(side_effect=Exception("Workflow error"))

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Test"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        result = await workflow.run(spec)

        assert result.fallback_used is True
        assert "both_failed" in (result.fallback_reason or "")
        assert result.execution_result is None


class TestAgentRunnerWorkflowIntegration:
    """Tests for workflow integration with AgentRunner."""

    @pytest.mark.asyncio
    async def test_runner_uses_legacy_when_workflow_disabled(self):
        """Runner should use _run_legacy when workflow is disabled."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="Hello!",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        ))

        runner = AgentRunner(provider)

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Hi"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        with patch.dict(os.environ, {}, clear=True):
            result = await runner.run(spec)

        assert result.stop_reason == "completed"
        assert result.final_content == "Hello!"

    @pytest.mark.asyncio
    async def test_runner_uses_workflow_when_enabled(self):
        """Runner should use workflow when NANOBOT_AGENT_WORKFLOW=1."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        runner = AgentRunner(provider)

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Hi"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        with patch("nanobot.agent.runner.is_workflow_enabled", return_value=True):
            with patch.object(runner, "_run_legacy") as mock_legacy:
                mock_legacy.return_value = AgentRunResult(
                    final_content="Workflow result",
                    messages=[],
                    stop_reason="completed",
                )

                with patch("nanobot.agent.runner.AgentWorkflow") as mock_workflow_class:
                    mock_workflow_instance = MagicMock()
                    mock_workflow_instance.run = AsyncMock(return_value=WorkflowResult(
                        used_workflow=True,
                        fallback_used=False,
                        execution_result=AgentRunResult(
                            final_content="Workflow pipeline result",
                            messages=[],
                            stop_reason="completed",
                        ),
                    ))
                    mock_workflow_class.return_value = mock_workflow_instance

                    result = await runner.run(spec)

        mock_workflow_class.assert_called_once()
        assert result.final_content == "Workflow pipeline result"

    @pytest.mark.asyncio
    async def test_runner_fallback_when_workflow_fails(self):
        """Runner should return result when workflow falls back to legacy."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        runner = AgentRunner(provider)

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Hi"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        with patch("nanobot.agent.runner.is_workflow_enabled", return_value=True):
            with patch.object(runner, "_run_legacy") as mock_legacy:
                mock_legacy.return_value = AgentRunResult(
                    final_content="Legacy fallback result",
                    messages=[],
                    stop_reason="completed",
                )

                with patch("nanobot.agent.runner.AgentWorkflow") as mock_workflow_class:
                    mock_workflow_instance = MagicMock()
                    mock_workflow_instance.run = AsyncMock(return_value=WorkflowResult(
                        used_workflow=False,
                        fallback_used=True,
                        fallback_reason="classification_failed",
                        execution_result=mock_legacy.return_value,
                    ))
                    mock_workflow_class.return_value = mock_workflow_instance

                    result = await runner.run(spec)

        assert result.final_content == "Legacy fallback result"

    @pytest.mark.asyncio
    async def test_runner_handles_both_failing(self):
        """Runner should return error when both workflow and legacy fail."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        runner = AgentRunner(provider)

        spec = AgentRunSpec(
            initial_messages=[{"role": "user", "content": "Hi"}],
            tools=MagicMock(),
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        with patch("nanobot.agent.runner.is_workflow_enabled", return_value=True):
            with patch("nanobot.agent.runner.AgentWorkflow") as mock_workflow_class:
                mock_workflow_instance = MagicMock()
                mock_workflow_instance.run = AsyncMock(return_value=WorkflowResult(
                    used_workflow=False,
                    fallback_used=True,
                    fallback_reason="both_failed",
                    execution_result=None,
                ))
                mock_workflow_class.return_value = mock_workflow_instance

                result = await runner.run(spec)

        assert result.stop_reason == "error"
        assert "Sorry, I encountered an error" in result.final_content
