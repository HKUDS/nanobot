"""Tests for the Tool Executor module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.workflow.executor import (
    ToolExecutor,
    ExecutionResult,
    ExecutionStatus,
)
from nanobot.agent.workflow.planner import ExecutionStep, StepType


class TestExecutionStatus:
    """Tests for ExecutionStatus enum."""
    
    def test_execution_status_values_are_unique(self):
        """Test that all ExecutionStatus values are unique."""
        values = [s.value for s in ExecutionStatus]
        assert len(values) == len(set(values))


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""
    
    def test_execution_result_creation(self):
        """Test creating an ExecutionResult."""
        result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="Directory listing",
            error_message="",
            retry_count=0,
        )
        
        assert result.step_index == 0
        assert result.step_type == StepType.TOOL_CALL
        assert result.tool_name == "list_dir"
        assert result.status == ExecutionStatus.SUCCESS
        assert result.success is True
        assert result.output == "Directory listing"
        assert result.error_message == ""
        assert result.retry_count == 0
    
    def test_execution_result_defaults(self):
        """Test ExecutionResult default values."""
        result = ExecutionResult(
            step_index=0,
            step_type=StepType.ANALYSIS,
        )
        
        assert result.tool_name == ""
        assert result.status == ExecutionStatus.PENDING
        assert result.success is False
        assert result.output is None
        assert result.error_message == ""
        assert result.exception is None
        assert result.start_time is None
        assert result.end_time is None
        assert result.retry_count == 0
        assert result.metadata == {}
    
    def test_to_dict(self):
        """Test converting ExecutionResult to dictionary."""
        result = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="File content",
            error_message="",
            metadata={"source": "test"},
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["step_index"] == 1
        assert result_dict["step_type"] == "tool_call"
        assert result_dict["tool_name"] == "read_file"
        assert result_dict["status"] == "success"
        assert result_dict["success"] is True
        assert result_dict["output"] == "File content"
        assert result_dict["error_message"] == ""
        assert result_dict["metadata"] == {"source": "test"}


class TestToolExecutor:
    """Tests for ToolExecutor class."""
    
    @pytest.fixture
    def executor(self):
        """Create a ToolExecutor instance."""
        return ToolExecutor()
    
    @pytest.fixture
    def mock_tools_registry(self):
        """Create a mocked tools registry."""
        registry = MagicMock()
        registry.get = MagicMock(return_value=MagicMock())
        registry.has = MagicMock(return_value=True)
        registry.execute = AsyncMock(return_value="tool result")
        return registry
    
    @pytest.mark.asyncio
    async def test_execute_step_tool_call_success(self, executor, mock_tools_registry):
        """Test executing a successful tool call step."""
        executor.tools_registry = mock_tools_registry
        
        step = ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            description="List directory",
            parameters={"path": "."},
        )
        
        result = await executor.execute_step(step)
        
        assert result.step_type == StepType.TOOL_CALL
        assert result.tool_name == "list_dir"
        assert result.start_time is not None
        assert result.end_time is not None
    
    @pytest.mark.asyncio
    async def test_execute_step_skill_load(self, executor):
        """Test executing a skill load step."""
        step = ExecutionStep(
            step_type=StepType.SKILL_LOAD,
            skill_name="memory",
            description="Load memory skill",
        )
        
        result = await executor.execute_step(step)
        
        assert result.step_type == StepType.SKILL_LOAD
        assert result.success is True
        assert "memory" in result.output or result.status == ExecutionStatus.SUCCESS
    
    @pytest.mark.asyncio
    async def test_execute_step_context_gather(self, executor):
        """Test executing a context gather step."""
        step = ExecutionStep(
            step_type=StepType.CONTEXT_GATHER,
            description="Gather context",
        )
        
        result = await executor.execute_step(step)
        
        assert result.step_type == StepType.CONTEXT_GATHER
        assert result.success is True
    
    @pytest.mark.asyncio
    async def test_execute_step_analysis(self, executor):
        """Test executing an analysis step."""
        step = ExecutionStep(
            step_type=StepType.ANALYSIS,
            description="Analyze results",
        )
        
        result = await executor.execute_step(step)
        
        assert result.step_type == StepType.ANALYSIS
        assert result.success is True
    
    @pytest.mark.asyncio
    async def test_execute_step_validation(self, executor):
        """Test executing a validation step."""
        step = ExecutionStep(
            step_type=StepType.VALIDATION,
            description="Validate results",
        )
        
        result = await executor.execute_step(step)
        
        assert result.step_type == StepType.VALIDATION
        assert result.success is True
    
    @pytest.mark.asyncio
    async def test_execute_step_no_tool_specified(self, executor, mock_tools_registry):
        """Test executing a tool call step with no tool specified."""
        executor.tools_registry = mock_tools_registry
        
        step = ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="",
            description="No tool",
        )
        
        result = await executor.execute_step(step)
        
        assert result.status == ExecutionStatus.SKIPPED
    
    @pytest.mark.asyncio
    async def test_execute_step_no_parameters(self, executor, mock_tools_registry):
        """Test executing a tool call step with no parameters."""
        executor.tools_registry = mock_tools_registry
        
        step = ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            description="List directory",
            parameters={},
        )
        
        result = await executor.execute_step(step)
        
        assert result.status == ExecutionStatus.SKIPPED or result.status == ExecutionStatus.SUCCESS
    
    def test_get_history(self, executor):
        """Test getting execution history."""
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        executor._execution_history = [result1, result2]
        
        history = executor.get_history()
        
        assert len(history) == 2
        assert history[0] == result1
        assert history[1] == result2
    
    def test_get_successful_results(self, executor):
        """Test getting only successful results."""
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        result3 = ExecutionResult(
            step_index=2,
            step_type=StepType.TOOL_CALL,
            tool_name="glob",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        
        executor._execution_history = [result1, result2, result3]
        
        successful = executor.get_successful_results()
        
        assert len(successful) == 2
        assert successful[0] == result1
        assert successful[1] == result3
    
    def test_get_failed_results(self, executor):
        """Test getting only failed results."""
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        executor._execution_history = [result1, result2]
        
        failed = executor.get_failed_results()
        
        assert len(failed) == 1
        assert failed[0] == result2
    
    def test_has_failures(self, executor):
        """Test checking if there are any failures."""
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        
        executor._execution_history = [result1]
        assert executor.has_failures() is False
        
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        executor._execution_history = [result1, result2]
        assert executor.has_failures() is True
    
    def test_has_partial_success(self, executor):
        """Test checking for partial success."""
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        executor._execution_history = [result1]
        assert executor.has_partial_success() is False
        
        executor._execution_history = [result1, result2]
        assert executor.has_partial_success() is True
        
        executor._execution_history = [result2]
        assert executor.has_partial_success() is False
