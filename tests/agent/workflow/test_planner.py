"""Tests for the Plan Builder module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.workflow.planner import (
    PlanBuilder,
    ExecutionPlan,
    ExecutionStep,
    StepType,
)
from nanobot.agent.workflow.router import TaskType


class TestStepType:
    """Tests for StepType enum."""
    
    def test_step_type_values_are_unique(self):
        """Test that all StepType values are unique."""
        values = [t.value for t in StepType]
        assert len(values) == len(set(values))
    
    def test_step_type_has_expected_types(self):
        """Test that StepType includes all expected types."""
        expected = [
            "tool_call",
            "skill_load",
            "context_gather",
            "analysis",
            "validation",
        ]
        actual = [t.value for t in StepType]
        for exp in expected:
            assert exp in actual


class TestExecutionStep:
    """Tests for ExecutionStep dataclass."""
    
    def test_execution_step_creation(self):
        """Test creating an ExecutionStep."""
        step = ExecutionStep(
            step_type=StepType.TOOL_CALL,
            tool_name="list_dir",
            description="List root directory",
            parameters={"path": ".", "recursive": True},
            expected_output="Directory listing",
            critical=True,
            max_retries=3,
        )
        
        assert step.step_type == StepType.TOOL_CALL
        assert step.tool_name == "list_dir"
        assert step.description == "List root directory"
        assert step.parameters == {"path": ".", "recursive": True}
        assert step.expected_output == "Directory listing"
        assert step.critical is True
        assert step.max_retries == 3
    
    def test_execution_step_defaults(self):
        """Test ExecutionStep default values."""
        step = ExecutionStep(
            step_type=StepType.ANALYSIS,
        )
        
        assert step.tool_name == ""
        assert step.skill_name == ""
        assert step.description == ""
        assert step.parameters == {}
        assert step.expected_output == ""
        assert step.critical is True
        assert step.depends_on == []
        assert step.retry_count == 0
        assert step.max_retries == 2


class TestExecutionPlan:
    """Tests for ExecutionPlan dataclass."""
    
    def test_execution_plan_creation(self):
        """Test creating an ExecutionPlan."""
        steps = [
            ExecutionStep(step_type=StepType.TOOL_CALL, tool_name="list_dir"),
            ExecutionStep(step_type=StepType.TOOL_CALL, tool_name="read_file"),
        ]
        
        plan = ExecutionPlan(
            task_type=TaskType.PROJECT_ANALYSIS,
            steps=steps,
            summary="Analyze project structure",
            constraints=["Read-only operations"],
            required_skills=[],
            estimated_complexity="medium",
        )
        
        assert plan.task_type == TaskType.PROJECT_ANALYSIS
        assert len(plan.steps) == 2
        assert plan.summary == "Analyze project structure"
        assert plan.constraints == ["Read-only operations"]
        assert plan.estimated_complexity == "medium"
    
    def test_execution_plan_defaults(self):
        """Test ExecutionPlan default values."""
        plan = ExecutionPlan(task_type=TaskType.UNKNOWN)
        
        assert plan.steps == []
        assert plan.summary == ""
        assert plan.constraints == []
        assert plan.required_skills == []
        assert plan.estimated_complexity == "medium"
        assert plan.metadata == {}
    
    def test_add_step(self):
        """Test adding steps to a plan."""
        plan = ExecutionPlan(task_type=TaskType.CODE_ANALYSIS)
        
        assert plan.has_steps() is False
        
        step1 = ExecutionStep(step_type=StepType.TOOL_CALL, tool_name="read_file")
        plan.add_step(step1)
        
        assert len(plan.steps) == 1
        assert plan.has_steps() is True
        
        step2 = ExecutionStep(step_type=StepType.ANALYSIS)
        plan.add_step(step2)
        
        assert len(plan.steps) == 2
        assert plan.steps[0] == step1
        assert plan.steps[1] == step2


class TestPlanBuilder:
    """Tests for PlanBuilder class."""
    
    @pytest.fixture
    def builder(self):
        """Create a PlanBuilder instance."""
        return PlanBuilder()
    
    @pytest.mark.asyncio
    async def test_build_project_analysis_plan(self, builder):
        """Test building a plan for project analysis."""
        plan = await builder._build_project_analysis_plan("分析这个项目")
        
        assert plan.task_type == TaskType.PROJECT_ANALYSIS
        assert len(plan.steps) > 0
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "list_dir" in tool_names or "glob" in tool_names
        
        assert "Respect workspace boundaries" in plan.constraints
        assert "Do not modify files during analysis" in plan.constraints
    
    @pytest.mark.asyncio
    async def test_build_file_operation_plan(self, builder):
        """Test building a plan for file operations."""
        plan = await builder._build_file_operation_plan("读取 README.md 文件")
        
        assert plan.task_type == TaskType.FILE_OPERATION
        assert len(plan.steps) > 0
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "read_file" in tool_names or "list_dir" in tool_names
        
        assert "Always validate file paths before operations" in plan.constraints
    
    @pytest.mark.asyncio
    async def test_build_search_plan(self, builder):
        """Test building a plan for search operations."""
        plan = await builder._build_search_plan("搜索包含 'TODO' 的文件")
        
        assert plan.task_type == TaskType.SEARCH
        assert len(plan.steps) > 0
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "grep" in tool_names or "glob" in tool_names
    
    @pytest.mark.asyncio
    async def test_build_web_search_plan(self, builder):
        """Test building a plan for web search."""
        plan = await builder._build_web_search_plan("搜索最新的 Python 新闻")
        
        assert plan.task_type == TaskType.WEB_SEARCH
        assert len(plan.steps) > 0
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "web_search" in tool_names or "web_fetch" in tool_names
    
    @pytest.mark.asyncio
    async def test_build_code_execution_plan(self, builder):
        """Test building a plan for code execution."""
        plan = await builder._build_code_execution_plan("运行测试命令")
        
        assert plan.task_type == TaskType.CODE_EXECUTION
        assert len(plan.steps) > 0
        
        step_types = [step.step_type for step in plan.steps]
        assert StepType.VALIDATION in step_types
        assert StepType.TOOL_CALL in step_types
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "exec" in tool_names
        
        assert "Always validate commands before execution" in plan.constraints
    
    @pytest.mark.asyncio
    async def test_build_debugging_plan(self, builder):
        """Test building a plan for debugging."""
        plan = await builder._build_debugging_plan("修复这个 bug")
        
        assert plan.task_type == TaskType.DEBUGGING
        assert len(plan.steps) > 0
        
        step_types = [step.step_type for step in plan.steps]
        assert StepType.ANALYSIS in step_types
        assert StepType.VALIDATION in step_types
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "read_file" in tool_names or "edit_file" in tool_names
    
    @pytest.mark.asyncio
    async def test_build_testing_plan(self, builder):
        """Test building a plan for testing."""
        plan = await builder._build_testing_plan("运行测试")
        
        assert plan.task_type == TaskType.TESTING
        assert len(plan.steps) > 0
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "exec" in tool_names or "read_file" in tool_names or "write_file" in tool_names
    
    @pytest.mark.asyncio
    async def test_build_documentation_plan(self, builder):
        """Test building a plan for documentation."""
        plan = await builder._build_documentation_plan("为这个函数添加文档")
        
        assert plan.task_type == TaskType.DOCUMENTATION
        assert len(plan.steps) > 0
        
        step_types = [step.step_type for step in plan.steps]
        assert StepType.ANALYSIS in step_types
        
        tool_names = [step.tool_name for step in plan.steps]
        assert "read_file" in tool_names or "edit_file" in tool_names
    
    @pytest.mark.asyncio
    async def test_build_general_plan(self, builder):
        """Test building a general plan."""
        plan = await builder._build_general_plan("你好", TaskType.GENERAL_ASSISTANCE)
        
        assert plan.task_type == TaskType.GENERAL_ASSISTANCE
        
        step_types = [step.step_type for step in plan.steps]
        assert StepType.ANALYSIS in step_types or len(plan.steps) == 0
    
    @pytest.mark.asyncio
    async def test_build_plan_with_mocked_provider(self):
        """Test building a plan with a mocked LLM provider."""
        mock_provider = MagicMock()
        builder = PlanBuilder(llm_provider=mock_provider)
        
        plan = await builder.build_plan(
            "分析这个项目",
            TaskType.PROJECT_ANALYSIS,
        )
        
        assert plan.task_type == TaskType.PROJECT_ANALYSIS
        assert len(plan.steps) > 0
