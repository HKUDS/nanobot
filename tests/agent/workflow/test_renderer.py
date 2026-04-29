"""Tests for the Report Renderer module."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from nanobot.agent.workflow.renderer import (
    ReportRenderer,
    RenderedReport,
)
from nanobot.agent.workflow.executor import ExecutionResult, ExecutionStatus
from nanobot.agent.workflow.planner import ExecutionPlan, ExecutionStep, StepType
from nanobot.agent.workflow.router import TaskType
from nanobot.agent.workflow.validator import ValidationResult, ValidationStatus


class TestRenderedReport:
    """Tests for RenderedReport dataclass."""
    
    def test_rendered_report_creation(self):
        """Test creating a RenderedReport."""
        report = RenderedReport(
            content="# Test Report\n\nThis is a test.",
            format="markdown",
            language="zh",
            sections=[{"title": "Summary", "content": "Test summary"}],
            metadata={"task_type": "project_analysis"},
        )
        
        assert "# Test Report" in report.content
        assert report.format == "markdown"
        assert report.language == "zh"
        assert len(report.sections) == 1
        assert report.metadata == {"task_type": "project_analysis"}
    
    def test_rendered_report_defaults(self):
        """Test RenderedReport default values."""
        report = RenderedReport(content="Test")
        
        assert report.content == "Test"
        assert report.format == "markdown"
        assert report.language == "auto"
        assert report.sections == []
        assert report.metadata == {}


class TestReportRenderer:
    """Tests for ReportRenderer class."""
    
    @pytest.fixture
    def renderer(self):
        """Create a ReportRenderer instance."""
        return ReportRenderer()
    
    def _create_execution_result(
        self,
        step_index: int,
        tool_name: str,
        success: bool,
        output: str = "",
        error_message: str = "",
    ) -> ExecutionResult:
        """Helper to create an ExecutionResult."""
        return ExecutionResult(
            step_index=step_index,
            step_type=StepType.TOOL_CALL,
            tool_name=tool_name,
            status=ExecutionStatus.SUCCESS if success else ExecutionStatus.FAILED,
            success=success,
            output=output,
            error_message=error_message,
        )
    
    @pytest.mark.asyncio
    async def test_render_success_report(self, renderer):
        """Test rendering a successful report."""
        results = [
            self._create_execution_result(0, "list_dir", True, output="file1.py\nfile2.py"),
            self._create_execution_result(1, "read_file", True, output="def main():\n    pass"),
        ]
        
        validation = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="All steps completed successfully",
            passed_checks=["list_dir: OK", "read_file: OK"],
        )
        
        report = await renderer.render(
            user_input="分析这个项目",
            task_type=TaskType.PROJECT_ANALYSIS,
            execution_results=results,
            validation_result=validation,
        )
        
        assert isinstance(report, RenderedReport)
        assert "#" in report.content
        assert "SUCCESS" in report.content or "成功" in report.content
        assert "list_dir" in report.content
    
    @pytest.mark.asyncio
    async def test_render_partial_success_report(self, renderer):
        """Test rendering a partial success report."""
        results = [
            self._create_execution_result(0, "list_dir", True, output="file1.py"),
            self._create_execution_result(1, "read_file", False, error_message="File not found"),
        ]
        
        validation = ValidationResult(
            status=ValidationStatus.PARTIAL_SUCCESS,
            success=False,
            message="Some steps succeeded, some failed",
            passed_checks=["list_dir: OK"],
            failed_checks=["read_file: File not found"],
            warnings=["Check file paths"],
        )
        
        report = await renderer.render(
            user_input="List and read files",
            task_type=TaskType.FILE_OPERATION,
            execution_results=results,
            validation_result=validation,
        )
        
        assert isinstance(report, RenderedReport)
        assert "PARTIAL" in report.content or "部分" in report.content
        assert "list_dir" in report.content
        assert "read_file" in report.content
        assert "File not found" in report.content
    
    @pytest.mark.asyncio
    async def test_render_failure_report(self, renderer):
        """Test rendering a failure report."""
        results = [
            self._create_execution_result(0, "list_dir", False, error_message="Permission denied"),
        ]
        
        validation = ValidationResult(
            status=ValidationStatus.FAILURE,
            success=False,
            message="All steps failed",
            errors=["Permission denied"],
        )
        
        report = await renderer.render(
            user_input="List files",
            task_type=TaskType.FILE_OPERATION,
            execution_results=results,
            validation_result=validation,
        )
        
        assert isinstance(report, RenderedReport)
        assert "FAILURE" in report.content or "失败" in report.content
        assert "Permission denied" in report.content
    
    @pytest.mark.asyncio
    async def test_render_with_plan(self, renderer):
        """Test rendering a report with an execution plan."""
        plan = ExecutionPlan(
            task_type=TaskType.PROJECT_ANALYSIS,
            summary="Analyze project structure",
            steps=[
                ExecutionStep(step_type=StepType.TOOL_CALL, tool_name="list_dir", description="List directory"),
                ExecutionStep(step_type=StepType.TOOL_CALL, tool_name="read_file", description="Read files"),
            ],
        )
        
        results = [
            self._create_execution_result(0, "list_dir", True, output="file1.py"),
        ]
        
        validation = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="Completed",
        )
        
        report = await renderer.render(
            user_input="Analyze project",
            task_type=TaskType.PROJECT_ANALYSIS,
            plan=plan,
            execution_results=results,
            validation_result=validation,
        )
        
        assert isinstance(report, RenderedReport)
        assert len(report.sections) > 0
    
    def test_detect_language_english(self, renderer):
        """Test detecting English language."""
        english_text = "Hello, how are you? This is a test."
        language = renderer._detect_language(english_text)
        assert language == "en"
    
    def test_detect_language_chinese(self, renderer):
        """Test detecting Chinese language."""
        chinese_text = "你好，这是一个测试。分析这个项目的结构。"
        language = renderer._detect_language(chinese_text)
        assert language == "zh"
    
    def test_detect_language_mixed(self, renderer):
        """Test detecting mixed language (should prefer Chinese if enough characters)."""
        mixed_text = "Hello, 分析这个项目。"
        language = renderer._detect_language(mixed_text)
        assert language in ("zh", "en")
    
    def test_render_validation_summary_english(self, renderer):
        """Test rendering validation summary in English."""
        result = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="All steps completed",
            passed_checks=["list_dir: OK"],
            failed_checks=[],
            warnings=[],
            errors=[],
        )
        
        summary = renderer._render_validation_summary(result, "en")
        
        assert "Execution Summary" in summary
        assert "Successful steps: 1" in summary
    
    def test_render_validation_summary_chinese(self, renderer):
        """Test rendering validation summary in Chinese."""
        result = ValidationResult(
            status=ValidationStatus.SUCCESS,
            success=True,
            message="所有步骤已完成",
            passed_checks=["list_dir: 成功"],
            failed_checks=[],
            warnings=[],
            errors=[],
        )
        
        summary = renderer._render_validation_summary(result, "zh")
        
        assert "执行摘要" in summary
        assert "成功步骤" in summary
    
    def test_render_execution_results(self, renderer):
        """Test rendering execution results."""
        results = [
            self._create_execution_result(0, "list_dir", True, output="file1.py\nfile2.py"),
            self._create_execution_result(1, "read_file", False, error_message="Not found"),
        ]
        
        rendered = renderer._render_execution_results(results, "en")
        
        assert "list_dir" in rendered
        assert "read_file" in rendered
        assert "file1.py" in rendered
        assert "Not found" in rendered
    
    def test_render_error_details(self, renderer):
        """Test rendering error details."""
        result = ValidationResult(
            status=ValidationStatus.FAILURE,
            success=False,
            errors=["Network error", "Timeout"],
            failed_checks=["Step 1: Failed"],
        )
        
        rendered = renderer._render_error_details(result, "en")
        
        assert "Error Details" in rendered
        assert "Network error" in rendered
        assert "Timeout" in rendered
    
    def test_render_warnings(self, renderer):
        """Test rendering warnings."""
        result = ValidationResult(
            status=ValidationStatus.PARTIAL_SUCCESS,
            success=False,
            warnings=["Check file paths", "Review permissions"],
        )
        
        rendered = renderer._render_warnings(result, "en")
        
        assert "Warnings" in rendered
        assert "Check file paths" in rendered
        assert "Review permissions" in rendered
    
    def test_render_footer(self, renderer):
        """Test rendering the footer."""
        footer_en = renderer._render_footer("en")
        footer_zh = renderer._render_footer("zh")
        
        assert "Nanobot Agent Workflow" in footer_en
        assert "Tips:" in footer_en
        assert "Nanobot Agent Workflow" in footer_zh
        assert "提示" in footer_zh
    
    def test_ensure_utf8_encoding(self, renderer):
        """Test ensuring UTF-8 encoding."""
        text_with_chinese = "这是中文测试"
        
        result = renderer._ensure_utf8_encoding(text_with_chinese)
        
        assert result == text_with_chinese
    
    def test_render_simple_error(self, renderer):
        """Test rendering a simple error message."""
        error_en = renderer.render_simple_error("Something went wrong", "en")
        error_zh = renderer.render_simple_error("出错了", "zh")
        
        assert "Error" in error_en
        assert "Something went wrong" in error_en
        assert "错误" in error_zh
        assert "出错了" in error_zh
