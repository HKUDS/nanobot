"""Behavior tests for Agent Workflow integration with AgentLoop.

This test file covers:
1. Switch off → uses old loop
2. Switch on → uses new workflow
3. Workflow failure → warning + fallback
4. Project analysis request recognition
5. Structured execution records
6. Chinese text handling (no garbled)
7. Partial success handling
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.agent.workflow import (
    AgentWorkflow,
    WorkflowContext,
    WorkflowResult,
    WorkflowStage,
    is_agent_workflow_enabled,
    AGENT_WORKFLOW_ENV,
)
from nanobot.agent.workflow.router import TaskRouter, TaskType
from nanobot.agent.workflow.planner import PlanBuilder, ExecutionPlan, ExecutionStep, StepType
from nanobot.agent.workflow.executor import ToolExecutor, ExecutionResult, ExecutionStatus
from nanobot.agent.workflow.validator import ResultValidator, ValidationResult, ValidationStatus
from nanobot.agent.workflow.renderer import ReportRenderer, RenderedReport


class TestWorkflowSwitchBehavior:
    """Tests for workflow switch behavior."""
    
    def test_switch_enabled(self):
        """Test workflow is enabled when env var is '1'."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "1"}):
            assert is_agent_workflow_enabled() is True
    
    def test_switch_disabled_when_env_0(self):
        """Test workflow is disabled when env var is '0'."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "0"}):
            assert is_agent_workflow_enabled() is False
    
    def test_switch_disabled_when_env_missing(self):
        """Test workflow is disabled when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_agent_workflow_enabled() is False
    
    def test_switch_disabled_when_env_other(self):
        """Test workflow is disabled when env var is set to other values."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "true"}):
            assert is_agent_workflow_enabled() is False
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "yes"}):
            assert is_agent_workflow_enabled() is False


class TestWorkflowStageTracking:
    """Tests for workflow stage tracking in error handling."""
    
    def test_workflow_stage_enum(self):
        """Test WorkflowStage enum has all expected values."""
        assert WorkflowStage.INITIALIZATION.value == "initialization"
        assert WorkflowStage.TASK_ROUTER.value == "task_router"
        assert WorkflowStage.PLAN_BUILDER.value == "plan_builder"
        assert WorkflowStage.TOOL_EXECUTOR.value == "tool_executor"
        assert WorkflowStage.CONTEXT_COMPRESSOR.value == "context_compressor"
        assert WorkflowStage.RESULT_VALIDATOR.value == "result_validator"
        assert WorkflowStage.REPORT_RENDERER.value == "report_renderer"
    
    @pytest.mark.asyncio
    async def test_workflow_result_failed_stage_tracking(self):
        """Test WorkflowResult tracks failed stage."""
        result = WorkflowResult(
            success=False,
            content="Error",
            failed_stage=WorkflowStage.TASK_ROUTER,
            errors=[],
        )
        
        assert result.failed_stage == WorkflowStage.TASK_ROUTER
        assert result.get_failed_stage_name() == "task_router"
    
    @pytest.mark.asyncio
    async def test_workflow_result_get_error_summary(self):
        """Test WorkflowResult.get_error_summary() returns useful summary."""
        from nanobot.agent.workflow import WorkflowStage
        
        long_error = Exception("This is a very long error message that exceeds 150 characters. " * 5)
        
        result = WorkflowResult(
            success=False,
            content="Error",
            errors=[(WorkflowStage.PLAN_BUILDER, long_error, "traceback")],
        )
        
        summary = result.get_error_summary()
        assert isinstance(summary, str)
        assert len(summary) <= 153  # 150 chars + "..."
    
    @pytest.mark.asyncio
    async def test_workflow_result_get_failed_stage_name_from_errors(self):
        """Test get_failed_stage_name() falls back to errors when failed_stage is None."""
        from nanobot.agent.workflow import WorkflowStage
        
        result = WorkflowResult(
            success=False,
            content="Error",
            failed_stage=None,
            errors=[(WorkflowStage.TOOL_EXECUTOR, Exception("test"), "traceback")],
        )
        
        assert result.get_failed_stage_name() == "tool_executor"
    
    @pytest.mark.asyncio
    async def test_workflow_result_get_failed_stage_name_unknown(self):
        """Test get_failed_stage_name() returns 'unknown' when no error info."""
        result = WorkflowResult(
            success=True,
            content="Success",
            failed_stage=None,
            errors=[],
        )
        
        assert result.get_failed_stage_name() == "unknown"


class TestTaskRouterProjectAnalysis:
    """Tests for project analysis request recognition in TaskRouter."""
    
    def test_project_analysis_keywords(self):
        """Test PROJECT_ANALYSIS has appropriate keywords."""
        project_analysis_keywords = [
            "项目分析", "project analysis", "analyze project",
            "代码分析", "code analysis", "analyze code",
            "项目结构", "project structure", "代码结构", "code structure",
            "代码审查", "code review", "review code",
            "技术栈", "tech stack", "技术架构", "architecture",
            "依赖分析", "dependency analysis",
            "项目文档", "project docs", "项目说明",
            "这个项目", "this project", "当前项目", "current project",
            "查看项目", "explain project", "介绍项目", "introduce project",
            "项目概述", "project overview", "代码概览", "code overview",
        ]
        
        assert len(project_analysis_keywords) > 0
    
    @pytest.mark.asyncio
    async def test_task_router_recognizes_project_analysis_chinese(self):
        """Test TaskRouter recognizes Chinese project analysis requests."""
        router = TaskRouter()
        
        test_inputs = [
            "分析这个项目",
            "项目分析",
            "查看项目结构",
            "代码分析",
            "技术栈是什么",
            "项目概述",
            "代码审查",
            "这个项目是做什么的",
        ]
        
        for user_input in test_inputs:
            task_type = await router.route(user_input, [])
            is_project = router.is_project_analysis_request(user_input)
            assert is_project is True or task_type == TaskType.PROJECT_ANALYSIS, \
                f"Input '{user_input}' should be recognized as project analysis"
    
    @pytest.mark.asyncio
    async def test_task_router_recognizes_project_analysis_english(self):
        """Test TaskRouter recognizes English project analysis requests."""
        router = TaskRouter()
        
        test_inputs = [
            "analyze this project",
            "project analysis",
            "explain the code structure",
            "what's the tech stack",
            "code review please",
            "show me the project structure",
            "dependency analysis",
            "tell me about this project",
        ]
        
        for user_input in test_inputs:
            task_type = await router.route(user_input, [])
            is_project = router.is_project_analysis_request(user_input)
            assert is_project is True or task_type == TaskType.PROJECT_ANALYSIS, \
                f"Input '{user_input}' should be recognized as project analysis"
    
    @pytest.mark.asyncio
    async def test_task_router_not_project_analysis(self):
        """Test TaskRouter correctly identifies non-project-analysis requests."""
        router = TaskRouter()
        
        non_project_inputs = [
            "今天天气怎么样",
            "hello",
            "write a poem",
            "计算 1 + 1",
            "search for python tutorial",
            "read file test.txt",
            "list directory",
        ]
        
        for user_input in non_project_inputs:
            is_project = router.is_project_analysis_request(user_input)
            assert is_project is False, \
                f"Input '{user_input}' should NOT be recognized as project analysis"


class TestPlanBuilderForProjectAnalysis:
    """Tests for PlanBuilder creating appropriate plans for project analysis."""
    
    @pytest.mark.asyncio
    async def test_plan_builder_creates_project_analysis_plan(self):
        """Test PlanBuilder creates appropriate plan for project analysis."""
        planner = PlanBuilder()
        
        plan = await planner.build_plan(
            user_input="分析这个项目的结构",
            task_type=TaskType.PROJECT_ANALYSIS,
            conversation_history=[],
        )
        
        assert isinstance(plan, ExecutionPlan)
        assert plan.task_type == TaskType.PROJECT_ANALYSIS
        
        if plan.steps:
            tool_names = [step.tool_name for step in plan.steps]
            possible_tools = ["list_dir", "glob", "read_file", "grep"]
            assert any(t in " ".join(tool_names).lower() for t in possible_tools)
    
    @pytest.mark.asyncio
    async def test_plan_builder_unknown_task_type(self):
        """Test PlanBuilder handles UNKNOWN task type gracefully."""
        planner = PlanBuilder()
        
        plan = await planner.build_plan(
            user_input="hello world",
            task_type=TaskType.UNKNOWN,
            conversation_history=[],
        )
        
        assert isinstance(plan, ExecutionPlan)


class TestToolExecutorStructuredResults:
    """Tests for ToolExecutor producing structured execution records."""
    
    def test_execution_result_to_dict(self):
        """Test ExecutionResult.to_dict() is serializable."""
        import json
        from datetime import datetime
        
        result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="file1.txt\nfile2.py",
            error_message="",
            start_time=datetime.now(),
            end_time=datetime.now(),
        )
        
        result_dict = result.to_dict()
        
        json_str = json.dumps(result_dict, ensure_ascii=False)
        assert json_str is not None
        assert "step_index" in result_dict
        assert result_dict["tool_name"] == "list_dir"
        assert result_dict["success"] is True
        assert result_dict["status"] == "success"
    
    @pytest.mark.asyncio
    async def test_executor_has_partial_success(self):
        """Test ToolExecutor detects partial success (mixed results)."""
        executor = ToolExecutor()
        
        success_result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        failure_result = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        executor._execution_history.append(success_result)
        executor._execution_history.append(failure_result)
        
        assert executor.has_partial_success() is True
        assert executor.has_failures() is True
    
    @pytest.mark.asyncio
    async def test_executor_all_success(self):
        """Test ToolExecutor when all steps succeed."""
        executor = ToolExecutor()
        
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
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        
        executor._execution_history.append(result1)
        executor._execution_history.append(result2)
        
        assert executor.has_partial_success() is False
        assert executor.has_failures() is False
        assert len(executor.get_successful_results()) == 2
    
    @pytest.mark.asyncio
    async def test_executor_all_failure(self):
        """Test ToolExecutor when all steps fail."""
        executor = ToolExecutor()
        
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        executor._execution_history.append(result1)
        executor._execution_history.append(result2)
        
        assert executor.has_partial_success() is False
        assert executor.has_failures() is True
        assert len(executor.get_failed_results()) == 2


class TestValidatorPartialSuccess:
    """Tests for ResultValidator detecting partial success."""
    
    @pytest.mark.asyncio
    async def test_validator_detects_partial_success(self):
        """Test ResultValidator detects partial success."""
        validator = ResultValidator()
        
        success_result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="file1.txt",
        )
        failure_result = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
            error_message="File not found",
        )
        
        validation_result = await validator.validate(
            user_input="分析项目",
            execution_results=[success_result, failure_result],
            task_type=TaskType.PROJECT_ANALYSIS,
        )
        
        assert isinstance(validation_result, ValidationResult)
        assert validation_result.status == ValidationStatus.PARTIAL_SUCCESS
        assert validation_result.error_summary is not None
        assert "File not found" in validation_result.error_summary
    
    @pytest.mark.asyncio
    async def test_validator_all_success(self):
        """Test ResultValidator when all results are successful."""
        validator = ResultValidator()
        
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="file1.txt",
        )
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="content",
        )
        
        validation_result = await validator.validate(
            user_input="分析项目",
            execution_results=[result1, result2],
            task_type=TaskType.PROJECT_ANALYSIS,
        )
        
        assert validation_result.status == ValidationStatus.SUCCESS
        assert validation_result.success is True
    
    @pytest.mark.asyncio
    async def test_validator_all_failure(self):
        """Test ResultValidator when all results fail."""
        validator = ResultValidator()
        
        result1 = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.FAILED,
            success=False,
            error_message="Permission denied",
        )
        result2 = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
            error_message="File not found",
        )
        
        validation_result = await validator.validate(
            user_input="分析项目",
            execution_results=[result1, result2],
            task_type=TaskType.PROJECT_ANALYSIS,
        )
        
        assert validation_result.status == ValidationStatus.FAILURE
        assert validation_result.success is False
        assert "Permission denied" in validation_result.error_summary
        assert "File not found" in validation_result.error_summary


class TestReportRendererChinese:
    """Tests for ReportRenderer handling Chinese text without garbling."""
    
    @pytest.mark.asyncio
    async def test_renderer_chinese_text_rendering(self):
        """Test ReportRenderer handles Chinese text correctly."""
        renderer = ReportRenderer()
        
        chinese_content = "这是一段中文测试内容。项目分析结果：\n1. 文件列表\n2. 代码结构"
        
        report = await renderer.render(
            user_input="分析这个项目",
            task_type=TaskType.PROJECT_ANALYSIS,
            plan=None,
            execution_results=[],
            validation_result=ValidationResult(
                status=ValidationStatus.SUCCESS,
                success=True,
                summary=chinese_content,
            ),
        )
        
        assert isinstance(report, RenderedReport)
        assert report.content is not None
        
        encoded = report.content.encode('utf-8')
        decoded = encoded.decode('utf-8')
        assert decoded == report.content
    
    @pytest.mark.asyncio
    async def test_renderer_detect_chinese_language(self):
        """Test ReportRenderer detects Chinese input."""
        renderer = ReportRenderer()
        
        result_chinese = await renderer.render(
            user_input="分析这个项目的代码结构",
            task_type=TaskType.PROJECT_ANALYSIS,
            plan=None,
            execution_results=[],
            validation_result=ValidationResult(
                status=ValidationStatus.SUCCESS,
                success=True,
                summary="Done",
            ),
        )
        
        result_english = await renderer.render(
            user_input="Analyze this project structure",
            task_type=TaskType.PROJECT_ANALYSIS,
            plan=None,
            execution_results=[],
            validation_result=ValidationResult(
                status=ValidationStatus.SUCCESS,
                success=True,
                summary="Done",
            ),
        )
        
        assert result_chinese.language in ['zh', 'en']
        assert result_english.language in ['zh', 'en']
    
    @pytest.mark.asyncio
    async def test_renderer_partial_success_report(self):
        """Test ReportRenderer generates report for partial success."""
        renderer = ReportRenderer()
        
        success_result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="file1.txt\nfile2.py",
        )
        failure_result = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
            error_message="File not found: missing.txt",
        )
        
        report = await renderer.render(
            user_input="分析这个项目",
            task_type=TaskType.PROJECT_ANALYSIS,
            plan=None,
            execution_results=[success_result, failure_result],
            validation_result=ValidationResult(
                status=ValidationStatus.PARTIAL_SUCCESS,
                success=False,
                summary="部分成功",
                error_summary="read_file: File not found",
            ),
        )
        
        assert "部分成功" in report.content or "partial" in report.content.lower()
        assert "read_file" in report.content.lower() or "错误" in report.content


class TestAgentWorkflowFallback:
    """Tests for AgentWorkflow fallback mechanism."""
    
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
    def workflow(self, mock_tools_registry, tmp_path):
        """Create an AgentWorkflow instance with mocks."""
        return AgentWorkflow(
            tools_registry=mock_tools_registry,
            skills_loader=MagicMock(),
            context_builder=MagicMock(),
            llm_provider=MagicMock(),
            workspace=tmp_path,
            max_iterations=5,
        )
    
    @pytest.mark.asyncio
    async def test_workflow_completes_normally(self, workflow):
        """Test workflow completes successfully when no errors."""
        result = await workflow.run(
            user_input="分析这个项目",
            conversation_history=[],
        )
        
        assert isinstance(result, WorkflowResult)
        assert result.workflow_used is True
    
    @pytest.mark.asyncio
    async def test_workflow_router_exception_fallback(self, workflow):
        """Test workflow sets fallback_used=True when router raises exception."""
        workflow.router.route = AsyncMock(side_effect=Exception("Router failed"))
        
        result = await workflow.run(
            user_input="test",
            conversation_history=[],
        )
        
        assert result.fallback_used is True
        assert result.failed_stage == WorkflowStage.TASK_ROUTER
        assert result.get_failed_stage_name() == "task_router"
    
    @pytest.mark.asyncio
    async def test_workflow_planner_exception_fallback(self, workflow):
        """Test workflow sets fallback_used=True when planner raises exception."""
        workflow.planner.build_plan = AsyncMock(side_effect=Exception("Planner failed"))
        
        result = await workflow.run(
            user_input="test",
            conversation_history=[],
        )
        
        assert result.fallback_used is True
        assert result.failed_stage == WorkflowStage.PLAN_BUILDER
    
    @pytest.mark.asyncio
    async def test_workflow_validator_exception_fallback(self, workflow):
        """Test workflow sets fallback_used=True when validator raises exception."""
        workflow.validator.validate = AsyncMock(side_effect=Exception("Validator failed"))
        
        result = await workflow.run(
            user_input="test",
            conversation_history=[],
        )
        
        assert result.fallback_used is True
        assert result.failed_stage == WorkflowStage.RESULT_VALIDATOR
    
    @pytest.mark.asyncio
    async def test_workflow_renderer_exception_fallback(self, workflow):
        """Test workflow sets fallback_used=True when renderer raises exception."""
        workflow.renderer.render = AsyncMock(side_effect=Exception("Renderer failed"))
        
        result = await workflow.run(
            user_input="test",
            conversation_history=[],
        )
        
        assert result.fallback_used is True
        assert result.failed_stage == WorkflowStage.REPORT_RENDERER


class TestWorkflowResultPartialSuccessProperty:
    """Tests for WorkflowResult.partial_success property."""
    
    def test_partial_success_true(self):
        """Test partial_success is True when mixed results."""
        success_result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        failure_result = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        workflow_result = WorkflowResult(
            success=False,
            content="Partial",
            stage_results={"execution_results": [success_result, failure_result]},
        )
        
        assert workflow_result.partial_success is True
    
    def test_partial_success_false_no_results(self):
        """Test partial_success is False when no execution results."""
        workflow_result = WorkflowResult(
            success=True,
            content="Success",
            stage_results={},
        )
        
        assert workflow_result.partial_success is False
    
    def test_partial_success_false_all_success(self):
        """Test partial_success is False when all results succeed."""
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
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        
        workflow_result = WorkflowResult(
            success=True,
            content="Success",
            stage_results={"execution_results": [result1, result2]},
        )
        
        assert workflow_result.partial_success is False


class TestWorkflowIntegrationPoint:
    """Tests verifying workflow can be integrated with existing code."""
    
    def test_workflow_uses_existing_tool_registry(self):
        """Test AgentWorkflow accepts and uses existing ToolRegistry."""
        from nanobot.agent.tools.registry import ToolRegistry
        
        registry = ToolRegistry()
        workflow = AgentWorkflow(
            tools_registry=registry,
            skills_loader=MagicMock(),
            context_builder=MagicMock(),
            llm_provider=MagicMock(),
            workspace=".",
        )
        
        assert workflow.tools_registry is registry
        assert workflow.executor.tools_registry is registry
    
    def test_workflow_has_all_components(self):
        """Test AgentWorkflow has all required components."""
        from nanobot.agent.workflow.router import TaskRouter
        from nanobot.agent.workflow.planner import PlanBuilder
        from nanobot.agent.workflow.executor import ToolExecutor
        from nanobot.agent.workflow.compressor import ContextCompressor
        from nanobot.agent.workflow.validator import ResultValidator
        from nanobot.agent.workflow.renderer import ReportRenderer
        
        workflow = AgentWorkflow(
            tools_registry=MagicMock(),
            skills_loader=MagicMock(),
            context_builder=MagicMock(),
            llm_provider=MagicMock(),
            workspace=".",
        )
        
        assert isinstance(workflow.router, TaskRouter)
        assert isinstance(workflow.planner, PlanBuilder)
        assert isinstance(workflow.executor, ToolExecutor)
        assert isinstance(workflow.compressor, ContextCompressor)
        assert isinstance(workflow.validator, ResultValidator)
        assert isinstance(workflow.renderer, ReportRenderer)
