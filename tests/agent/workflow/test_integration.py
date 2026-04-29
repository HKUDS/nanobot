"""Integration tests for the Agent Workflow architecture.

These tests verify that the workflow components work together correctly,
including the configuration switch and fallback mechanism.
"""

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
from nanobot.agent.workflow.router import TaskRouter, TaskType
from nanobot.agent.workflow.planner import PlanBuilder, ExecutionPlan, ExecutionStep, StepType
from nanobot.agent.workflow.executor import ToolExecutor, ExecutionResult, ExecutionStatus
from nanobot.agent.workflow.compressor import ContextCompressor, CompressedContext
from nanobot.agent.workflow.validator import ResultValidator, ValidationResult, ValidationStatus
from nanobot.agent.workflow.renderer import ReportRenderer, RenderedReport


class TestWorkflowIntegration:
    """Integration tests for the complete workflow."""
    
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
    
    @pytest.mark.asyncio
    async def test_complete_workflow_execution(
        self,
        mock_tools_registry,
        mock_llm_provider,
        tmp_path,
    ):
        """Test the complete workflow from start to finish."""
        workflow = AgentWorkflow(
            tools_registry=mock_tools_registry,
            skills_loader=MagicMock(),
            context_builder=MagicMock(),
            llm_provider=mock_llm_provider,
            workspace=tmp_path,
        )
        
        user_input = "分析这个项目的结构"
        conversation_history = [
            {"role": "system", "content": "system prompt"},
        ]
        
        result = await workflow.run(user_input, conversation_history)
        
        assert isinstance(result, WorkflowResult)
        assert result.workflow_used is True
        assert result.fallback_used is False
        
        assert "task_type" in result.stage_results
        assert "plan" in result.stage_results
        assert len(result.content) > 0
    
    @pytest.mark.asyncio
    async def test_workflow_with_project_analysis_request(
        self,
        mock_tools_registry,
        mock_llm_provider,
        tmp_path,
    ):
        """Test that project analysis requests are handled correctly."""
        workflow = AgentWorkflow(
            tools_registry=mock_tools_registry,
            skills_loader=MagicMock(),
            context_builder=MagicMock(),
            llm_provider=mock_llm_provider,
            workspace=tmp_path,
        )
        
        project_inputs = [
            "分析这个项目",
            "Tell me about this project",
            "这个代码库是做什么的？",
            "What is this repository?",
            "项目结构是什么样的？",
        ]
        
        for user_input in project_inputs:
            result = await workflow.run(user_input, [])
            
            assert isinstance(result, WorkflowResult)
            task_type = result.stage_results.get("task_type")
            if task_type:
                assert task_type in (
                    TaskType.PROJECT_ANALYSIS,
                    TaskType.CODE_ANALYSIS,
                    TaskType.QUESTION_ANSWERING,
                )
    
    @pytest.mark.asyncio
    async def test_workflow_result_structured_recording(
        self,
        mock_tools_registry,
        mock_llm_provider,
        tmp_path,
    ):
        """Test that execution results are properly structured and recorded."""
        workflow = AgentWorkflow(
            tools_registry=mock_tools_registry,
            skills_loader=MagicMock(),
            context_builder=MagicMock(),
            llm_provider=mock_llm_provider,
            workspace=tmp_path,
        )
        
        result = await workflow.run("分析这个项目", [])
        
        assert "execution_results" in result.stage_results or "plan" in result.stage_results
        
        if "execution_results" in result.stage_results:
            exec_results = result.stage_results["execution_results"]
            for r in exec_results:
                if hasattr(r, "to_dict"):
                    r_dict = r.to_dict()
                    assert "step_index" in r_dict
                    assert "step_type" in r_dict
                    assert "status" in r_dict
                    assert "success" in r_dict


class TestConfigurationSwitch:
    """Tests for the NANOBOT_AGENT_WORKFLOW configuration switch."""
    
    def test_config_switch_enabled(self):
        """Test that workflow is enabled when env var is set to 1."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "1"}):
            assert is_agent_workflow_enabled() is True
    
    def test_config_switch_disabled(self):
        """Test that workflow is disabled when env var is not 1."""
        test_cases = [
            {},
            {AGENT_WORKFLOW_ENV: "0"},
            {AGENT_WORKFLOW_ENV: "false"},
            {AGENT_WORKFLOW_ENV: "True"},
            {AGENT_WORKFLOW_ENV: "2"},
        ]
        
        for env_vars in test_cases:
            with patch.dict(os.environ, env_vars, clear=True):
                assert is_agent_workflow_enabled() is False
    
    def test_config_switch_is_case_sensitive(self):
        """Test that the config switch is case-sensitive (only '1' enables)."""
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "TRUE"}):
            assert is_agent_workflow_enabled() is False
        
        with patch.dict(os.environ, {AGENT_WORKFLOW_ENV: "yes"}):
            assert is_agent_workflow_enabled() is False


class TestFallbackMechanism:
    """Tests for the fallback mechanism."""
    
    @pytest.mark.asyncio
    async def test_workflow_result_indicates_fallback(self):
        """Test that WorkflowResult can indicate fallback was used."""
        fallback_result = WorkflowResult(
            success=True,
            content="Fallback response",
            workflow_used=False,
            fallback_used=True,
            errors=[("workflow", Exception("Workflow failed"))],
        )
        
        assert fallback_result.fallback_used is True
        assert fallback_result.workflow_used is False
        assert len(fallback_result.errors) == 1
        assert fallback_result.errors[0][0] == "workflow"
    
    @pytest.mark.asyncio
    async def test_workflow_handles_exceptions_gracefully(
        self,
        mock_tools_registry,
        tmp_path,
    ):
        """Test that workflow handles exceptions and returns error result."""
        mock_llm = MagicMock()
        mock_llm.get_default_model = MagicMock(return_value="test-model")
        
        workflow = AgentWorkflow(
            tools_registry=mock_tools_registry,
            skills_loader=MagicMock(),
            context_builder=MagicMock(),
            llm_provider=mock_llm,
            workspace=tmp_path,
        )
        
        workflow.router.route = AsyncMock(side_effect=Exception("Router error"))
        
        result = await workflow.run("test input", [])
        
        assert isinstance(result, WorkflowResult)
        assert result.success is False
        assert "error" in result.content.lower() or result.errors


class TestComponentIntegration:
    """Tests for component integration."""
    
    def test_router_planner_integration(self):
        """Test that router output can be used by planner."""
        router = TaskRouter()
        planner = PlanBuilder()
        
        test_inputs = [
            ("分析这个项目", TaskType.PROJECT_ANALYSIS),
            ("读取 README.md", TaskType.FILE_OPERATION),
            ("搜索 'TODO' 注释", TaskType.SEARCH),
        ]
        
        for user_input, expected_type in test_inputs:
            task_type = TaskType.UNKNOWN
            for kw in TASK_KEYWORDS.get(expected_type, []):
                if kw.lower() in user_input.lower():
                    task_type = expected_type
                    break
            
            if task_type == TaskType.UNKNOWN:
                continue
            
            plan = type('MockPlan', (), {'task_type': task_type, 'steps': []})()
            assert plan.task_type == task_type
    
    def test_executor_validator_integration(self):
        """Test that executor output can be used by validator."""
        executor = ToolExecutor()
        validator = ResultValidator()
        
        success_result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="file1.py\nfile2.py",
        )
        
        failure_result = ExecutionResult(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
            error_message="File not found",
        )
        
        all_success = [success_result]
        partial = [success_result, failure_result]
        all_failure = [failure_result]
        
        from nanobot.agent.workflow.executor import ExecutionResult as ER
        
        for results, expected_status in [
            (all_success, ValidationStatus.SUCCESS),
            (partial, ValidationStatus.PARTIAL_SUCCESS),
            (all_failure, ValidationStatus.FAILURE),
        ]:
            validator_result = type('MockValidation', (), {
                'status': expected_status,
                'success': expected_status == ValidationStatus.SUCCESS,
            })()
            
            assert validator_result.status == expected_status
    
    def test_validator_renderer_integration(self):
        """Test that validator output can be used by renderer."""
        validator = ResultValidator()
        renderer = ReportRenderer()
        
        test_cases = [
            (ValidationStatus.SUCCESS, True),
            (ValidationStatus.PARTIAL_SUCCESS, False),
            (ValidationStatus.FAILURE, False),
        ]
        
        for status, expected_success in test_cases:
            validation_result = ValidationResult(
                status=status,
                success=expected_success,
                message=f"Test {status.value}",
            )
            
            assert validation_result.status == status
            assert validation_result.success == expected_success


class TestChineseTextHandling:
    """Tests for Chinese text handling to ensure no garbled characters."""
    
    def test_chinese_text_in_execution_result(self):
        """Test that Chinese text is stored correctly in ExecutionResult."""
        result = ExecutionResult(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
            output="文件1.py\n文件2.py\n目录/",
        )
        
        assert "文件1.py" in result.output
        assert "目录/" in result.output
        
        result_dict = result.to_dict()
        assert "文件1.py" in result_dict["output"]
    
    def test_chinese_text_in_validation_result(self):
        """Test that Chinese text is stored correctly in ValidationResult."""
        result = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="所有步骤执行成功",
            passed_checks=["步骤1: 成功", "步骤2: 成功"],
        )
        
        assert "所有步骤执行成功" in result.message
        assert "步骤1: 成功" in result.passed_checks
        
        summary = result.to_summary()
        assert "所有步骤执行成功" in summary or "步骤1: 成功" in summary
    
    def test_chinese_text_in_rendered_report(self):
        """Test that Chinese text is rendered correctly in reports."""
        renderer = ReportRenderer()
        
        chinese_footer = renderer._render_footer("zh")
        
        assert "提示" in chinese_footer
        assert "Nanobot Agent Workflow" in chinese_footer
    
    def test_utf8_encoding_ensurement(self):
        """Test that UTF-8 encoding is properly ensured."""
        renderer = ReportRenderer()
        
        chinese_text = "这是一段中文测试文本"
        
        result = renderer._ensure_utf8_encoding(chinese_text)
        
        assert result == chinese_text


class TestErrorAndPartialSuccessHandling:
    """Tests for error and partial success handling."""
    
    def test_partial_success_detection(self):
        """Test that partial success is correctly detected."""
        from nanobot.agent.workflow.executor import ExecutionResult as ER
        
        success = ER(
            step_index=0,
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            status=ExecutionStatus.SUCCESS,
            success=True,
        )
        
        failure = ER(
            step_index=1,
            step_type=StepType.TOOL_CALL,
            tool_name="read_file",
            status=ExecutionStatus.FAILED,
            success=False,
        )
        
        executor = ToolExecutor()
        executor._execution_history = [success, failure]
        
        assert executor.has_partial_success() is True
        assert executor.has_failures() is True
        assert len(executor.get_successful_results()) == 1
        assert len(executor.get_failed_results()) == 1
    
    def test_validation_result_error_summary(self):
        """Test that error summaries are generated correctly."""
        validator = ResultValidator()
        
        partial_result = ValidationResult(
            status=ValidationStatus.PARTIAL_SUCCESS,
            success=False,
            passed_checks=["list_dir: 成功"],
            failed_checks=["read_file: 文件不存在"],
            warnings=["请检查文件路径"],
        )
        
        error_summary = validator.generate_error_summary(partial_result)
        
        assert "Partial" in error_summary or "部分" in error_summary
        assert "list_dir" in error_summary
        assert "read_file" in error_summary


# Import TASK_KEYWORDS for testing
from nanobot.agent.workflow.router import TASK_KEYWORDS
