"""Tests for the Agent Workflow main module."""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.agent.workflow import (
    AgentWorkflow,
    WorkflowContext,
    WorkflowResult,
    is_agent_workflow_enabled,
    AGENT_WORKFLOW_ENV,
)
from nanobot.agent.workflow.router import TaskType
from nanobot.agent.workflow.planner import StepType
from nanobot.agent.workflow.executor import ExecutionStatus
from nanobot.agent.workflow.validator import ValidationStatus


class TestIsAgentWorkflowEnabled:
    """Tests for the is_agent_workflow_enabled function."""
    
    def test_enabled_when_env_set_to_1(self):
        """Test workflow is enabled when env var is '1'."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "1"}):
            assert is_agent_workflow_enabled() is True
    
    def test_disabled_when_env_set_to_0(self):
        """Test workflow is disabled when env var is '0'."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "0"}):
            assert is_agent_workflow_enabled() is False
    
    def test_disabled_when_env_not_set(self):
        """Test workflow is disabled when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_agent_workflow_enabled() is False
    
    def test_disabled_when_env_set_to_other_value(self):
        """Test workflow is disabled when env var is set to other values."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "true"}):
            assert is_agent_workflow_enabled() is False


class TestWorkflowContext:
    """Tests for WorkflowContext dataclass."""
    
    def test_workflow_context_creation(self):
        """Test creating a WorkflowContext."""
        ctx = WorkflowContext(
            original_input="分析这个项目",
            task_type=TaskType.PROJECT_ANALYSIS,
        )
        
        assert ctx.original_input == "分析这个项目"
        assert ctx.task_type == TaskType.PROJECT_ANALYSIS
        assert ctx.plan is None
        assert ctx.execution_results == []
        assert ctx.compressed_context is None
        assert ctx.validation_result is None
        assert ctx.final_report is None
        assert ctx.metadata == {}
        assert ctx.errors == []
    
    def test_add_error(self):
        """Test adding errors to context."""
        ctx = WorkflowContext(original_input="test")
        
        assert ctx.has_errors() is False
        
        ctx.add_error("router", Exception("Test error"))
        
        assert ctx.has_errors() is True
        assert len(ctx.errors) == 1
        assert ctx.errors[0][0] == "router"
        assert isinstance(ctx.errors[0][1], Exception)
    
    def test_get_last_error(self):
        """Test getting the last error."""
        ctx = WorkflowContext(original_input="test")
        
        assert ctx.get_last_error() is None
        
        ctx.add_error("stage1", Exception("First error"))
        ctx.add_error("stage2", Exception("Second error"))
        
        last = ctx.get_last_error()
        assert last is not None
        assert last[0] == "stage2"
        assert "Second error" in str(last[1])


class TestWorkflowResult:
    """Tests for WorkflowResult dataclass."""
    
    def test_workflow_result_creation(self):
        """Test creating a WorkflowResult."""
        result = WorkflowResult(
            success=True,
            content="Task completed successfully",
            workflow_used=True,
            fallback_used=False,
            stage_results={"router": {"task_type": "project_analysis"},
            errors=[],
        )
        
        assert result.success is True
        assert result.content == "Task completed successfully"
        assert result.workflow_used is True
        assert result.fallback_used is False
        assert "router" in result.stage_results
        assert result.errors == []
    
    def test_partial_success_property(self):
        """Test the partial_success property."""
        from nanobot.agent.workflow.executor import ExecutionResult as ER
        
        result1 = ER(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        result2 = ER(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        workflow_result = WorkflowResult(
            success=False,
            content="Partial success",
            stage_results={"execution_results": [result1, result2]},
        )
        
        assert workflow_result.partial_success is True
    
    def test_partial_success_property_no_results(self):
        """Test partial_success when no execution results."""
        workflow_result = WorkflowResult(
            success=True,
            content="Success",
            stage_results={},
        )
        
        assert workflow_result.partial_success is False
    
    def test_partial_success_property_all_success(self):
        """Test partial_success when all results are successful."""
        from nanobot.agent.workflow.executor import ExecutionResult as ER
        
        result1 = ER(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        
        workflow_result = WorkflowResult(
            success=True,
            content="Success",
            stage_results={"execution_results": [result1]},
        )
        
        assert workflow_result.partial_success is False


class TestAgentWorkflow:
    """Tests for AgentWorkflow class."""
    
    @pytest.fixture
    def mock_tools_registry(self):
        """Create a mocked tools registry."""
        registry = MagicMock()
        registry.get = MagicMock(return_value=MagicMock())
        registry.has = MagicMock(return_value=True)
        registry.execute = AsyncMock(return_value="tool result")
        registry.get_definitions = MagicMock(return_value=[])
        return registry
    
    @pytest.fixture
    def mock_skills_loader(self):
        """Create a mocked skills loader."""
        loader = MagicMock()
        loader.list_skills = MagicMock(return_value=[])
        return loader
    
    @pytest.fixture
    def mock_context_builder(self):
        """Create a mocked context builder."""
        builder = MagicMock()
        builder.build_system_prompt = MagicMock(return_value="system prompt")
        return builder
    
    @pytest.fixture
    def mock_llm_provider(self):
        """Create a mocked LLM provider."""
        provider = MagicMock()
        provider.get_default_model = MagicMock(return_value="test-model")
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(
                content="Test response",
                tool_calls=[],
                usage={},
            )
        )
        return provider
    
    @pytest.fixture
    def workflow(
        self,
        mock_tools_registry,
        mock_skills_loader,
        mock_context_builder,
        mock_llm_provider,
        tmp_path,
    ):
        """Create an AgentWorkflow instance with mocks."""
        return AgentWorkflow(
            tools_registry=mock_tools_registry,
            skills_loader=mock_skills_loader,
            context_builder=mock_context_builder,
            llm_provider=mock_llm_provider,
            workspace=tmp_path,
            max_iterations=5,
        )
    
    @pytest.mark.asyncio
    async def test_workflow_initialization(self, workflow):
        """Test that the workflow initializes correctly."""
        assert workflow.tools_registry is not None
        assert workflow.llm_provider is not None
        assert workflow.max_iterations == 5
        
        assert workflow.router is not None
        assert workflow.planner is not None
        assert workflow.executor is not None
        assert workflow.compressor is not None
        assert workflow.validator is not None
        assert workflow.renderer is not None
    
    @pytest.mark.asyncio
    async def test_run_workflow_basic(self, workflow):
        """Test running the workflow with basic input."""
        result = await workflow.run(
            user_input="分析这个项目",
            conversation_history=[],
        )
        
        assert isinstance(result, WorkflowResult)
        assert result.workflow_used is True
        assert result.fallback_used is False
        assert "task_type" in result.stage_results
        assert "plan" in result.stage_results
    
    @pytest.mark.asyncio
    async def test_run_workflow_with_mocked_router(self, workflow):
        """Test running workflow with mocked router."""
        workflow.router.route = AsyncMock(return_value=TaskType.PROJECT_ANALYSIS)
        
        result = await workflow.run(
            user_input="Tell me about this project",
            conversation_history=[],
        )
        
        assert isinstance(result, WorkflowResult)
        workflow.router.route.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_workflow_with_progress_callback(self, workflow):
        """Test running workflow with progress callback."""
        progress_updates = []
        
        async def on_progress(content, **kwargs):
            progress_updates.append(content)
        
        result = await workflow.run(
            user_input="分析这个项目",
            conversation_history=[],
            on_progress=on_progress,
        )
        
        assert isinstance(result, WorkflowResult)
    
    def test_workflow_components_integration(self):
        """Test that all workflow components are properly integrated."""
        from nanobot.agent.workflow.router import TaskRouter
        from nanobot.agent.workflow.planner import PlanBuilder
        from nanobot.agent.workflow.executor import ToolExecutor
        from nanobot.agent.workflow.compressor import ContextCompressor
        from nanobot.agent.workflow.validator import ResultValidator
        from nanobot.agent.workflow.renderer import ReportRenderer
        
        from nanobot.agent.workflow import AgentWorkflow
        
        mock_registry = MagicMock()
        mock_skills = MagicMock()
        mock_context = MagicMock()
        mock_llm = MagicMock()
        
        workflow = AgentWorkflow(
            tools_registry=mock_registry,
            skills_loader=mock_skills,
            context_builder=mock_context,
            llm_provider=mock_llm,
            workspace=".",
        )
        
        assert isinstance(workflow.router, TaskRouter)
        assert isinstance(workflow.planner, PlanBuilder)
        assert isinstance(workflow.executor, ToolExecutor)
        assert isinstance(workflow.compressor, ContextCompressor)
        assert isinstance(workflow.validator, ResultValidator)
        assert isinstance(workflow.renderer, ReportRenderer)
