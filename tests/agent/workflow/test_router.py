"""Tests for the Task Router module."""

from __future__ import annotations

import pytest

from nanobot.agent.workflow.router import (
    TaskRouter,
    TaskType,
    RoutingResult,
    TASK_KEYWORDS,
)


class TestTaskType:
    """Tests for TaskType enum."""
    
    def test_task_type_values_are_unique(self):
        """Test that all TaskType values are unique."""
        values = [t.value for t in TaskType]
        assert len(values) == len(set(values))
    
    def test_task_type_has_expected_types(self):
        """Test that TaskType includes all expected types."""
        expected = [
            "code_analysis",
            "file_operation",
            "search",
            "web_search",
            "code_execution",
            "question_answering",
            "project_analysis",
            "debugging",
            "refactoring",
            "documentation",
            "testing",
            "deployment",
            "configuration",
            "general_assistance",
            "unknown",
        ]
        actual = [t.value for t in TaskType]
        for exp in expected:
            assert exp in actual


class TestTaskRouter:
    """Tests for TaskRouter class."""
    
    @pytest.fixture
    def router(self):
        """Create a TaskRouter instance."""
        return TaskRouter()
    
    @pytest.mark.asyncio
    async def test_route_project_analysis(self, router):
        """Test that project analysis requests are correctly identified."""
        inputs = [
            "分析这个项目",
            "Tell me about this project",
            "What is this repository?",
            "项目结构是什么样的？",
            "Analyze the codebase",
            "理解这个项目",
        ]
        
        for user_input in inputs:
            task_type = await router.route(user_input)
            assert task_type in (TaskType.PROJECT_ANALYSIS, TaskType.CODE_ANALYSIS, TaskType.QUESTION_ANSWERING)
    
    @pytest.mark.asyncio
    async def test_route_file_operation(self, router):
        """Test that file operation requests are correctly identified."""
        inputs = [
            "读取这个文件",
            "Read the file README.md",
            "编辑 main.py",
            "Edit config.json",
            "列出目录内容",
            "List files in this directory",
        ]
        
        for user_input in inputs:
            task_type = await router.route(user_input)
            assert task_type in (TaskType.FILE_OPERATION, TaskType.SEARCH)
    
    @pytest.mark.asyncio
    async def test_route_search(self, router):
        """Test that search requests are correctly identified."""
        inputs = [
            "搜索包含 'def test' 的文件",
            "Find all Python files",
            "grep for 'import'",
            "查找文件",
            "Search for 'TODO' comments",
        ]
        
        for user_input in inputs:
            task_type = await router.route(user_input)
            assert task_type in (TaskType.SEARCH, TaskType.FILE_OPERATION)
    
    @pytest.mark.asyncio
    async def test_route_web_search(self, router):
        """Test that web search requests are correctly identified."""
        inputs = [
            "搜索最新的 Python 新闻",
            "Search the web for AI news",
            "Web search for machine learning",
            "在网上查找",
        ]
        
        for user_input in inputs:
            task_type = await router.route(user_input)
            assert task_type in (TaskType.WEB_SEARCH, TaskType.SEARCH, TaskType.QUESTION_ANSWERING)
    
    @pytest.mark.asyncio
    async def test_route_code_execution(self, router):
        """Test that code execution requests are correctly identified."""
        inputs = [
            "运行这个脚本",
            "Run the test command",
            "执行 pip install",
            "Execute this shell command",
        ]
        
        for user_input in inputs:
            task_type = await router.route(user_input)
            assert task_type in (TaskType.CODE_EXECUTION, TaskType.TESTING)
    
    @pytest.mark.asyncio
    async def test_route_debugging(self, router):
        """Test that debugging requests are correctly identified."""
        inputs = [
            "修复这个 bug",
            "Debug this error",
            "为什么这个不工作？",
            "Fix the issue",
            "解决这个问题",
        ]
        
        for user_input in inputs:
            task_type = await router.route(user_input)
            assert task_type in (TaskType.DEBUGGING, TaskType.QUESTION_ANSWERING)
    
    @pytest.mark.asyncio
    async def test_route_question_answering(self, router):
        """Test that question answering requests are correctly identified."""
        inputs = [
            "这是什么？",
            "What is this?",
            "如何使用这个？",
            "How does this work?",
            "你能帮我吗？",
            "Can you help me?",
        ]
        
        for user_input in inputs:
            task_type = await router.route(user_input)
            assert task_type in (
                TaskType.QUESTION_ANSWERING,
                TaskType.GENERAL_ASSISTANCE,
                TaskType.CODE_ANALYSIS,
            )
    
    def test_is_project_analysis_request(self, router):
        """Test the is_project_analysis_request method."""
        project_inputs = [
            "分析这个项目",
            "Tell me about this project",
            "What is this repository?",
            "项目结构",
            "代码库概述",
            "understand this project",
            "analyze this codebase",
        ]
        
        for user_input in project_inputs:
            result = router.is_project_analysis_request(user_input)
            assert result is True or "project" in user_input.lower()
        
        non_project_inputs = [
            "修改这个文件",
            "Run the tests",
            "edit config.json",
            "读取 README.md",
        ]
        
        for user_input in non_project_inputs:
            result = router.is_project_analysis_request(user_input)
            if "project" not in user_input.lower():
                assert result is False


class TestRoutingResult:
    """Tests for RoutingResult dataclass."""
    
    def test_routing_result_creation(self):
        """Test creating a RoutingResult."""
        result = RoutingResult(
            task_type=TaskType.PROJECT_ANALYSIS,
            confidence=0.85,
            keywords=["project", "analysis"],
            reasoning="Matched project keywords",
            metadata={"source": "keyword_matching"},
        )
        
        assert result.task_type == TaskType.PROJECT_ANALYSIS
        assert result.confidence == 0.85
        assert result.keywords == ["project", "analysis"]
        assert result.reasoning == "Matched project keywords"
        assert result.metadata == {"source": "keyword_matching"}
    
    def test_routing_result_defaults(self):
        """Test RoutingResult default values."""
        result = RoutingResult(
            task_type=TaskType.UNKNOWN,
            confidence=0.0,
        )
        
        assert result.keywords == []
        assert result.reasoning == ""
        assert result.metadata == {}


class TestTaskKeywords:
    """Tests for TASK_KEYWORDS dictionary."""
    
    def test_all_task_types_have_keywords(self):
        """Test that all TaskType values have keywords defined."""
        for task_type in TaskType:
            if task_type != TaskType.UNKNOWN:
                assert task_type in TASK_KEYWORDS
    
    def test_keywords_are_lists(self):
        """Test that keywords are stored as lists."""
        for task_type, keywords in TASK_KEYWORDS.items():
            assert isinstance(keywords, list)
            assert len(keywords) > 0
