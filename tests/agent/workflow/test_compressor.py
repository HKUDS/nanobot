"""Tests for the Context Compressor module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.workflow.compressor import (
    ContextCompressor,
    CompressedContext,
)
from nanobot.agent.workflow.executor import ExecutionResult, ExecutionStatus
from nanobot.agent.workflow.planner import StepType


class TestCompressedContext:
    """Tests for CompressedContext dataclass."""
    
    def test_compressed_context_creation(self):
        """Test creating a CompressedContext."""
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
        ]
        
        context = CompressedContext(
            compressed_messages=messages,
            summary="Context compressed",
            kept_messages_count=2,
            removed_messages_count=5,
            compressed_tool_results={"list_dir": "directory listing"},
            important_keywords=["project", "analysis"],
            metadata={"source": "test"},
        )
        
        assert context.compressed_messages == messages
        assert context.summary == "Context compressed"
        assert context.kept_messages_count == 2
        assert context.removed_messages_count == 5
        assert context.compressed_tool_results == {"list_dir": "directory listing"}
        assert context.important_keywords == ["project", "analysis"]
        assert context.metadata == {"source": "test"}
    
    def test_compressed_context_defaults(self):
        """Test CompressedContext default values."""
        context = CompressedContext()
        
        assert context.compressed_messages == []
        assert context.summary == ""
        assert context.kept_messages_count == 0
        assert context.removed_messages_count == 0
        assert context.compressed_tool_results == {}
        assert context.important_keywords == []
        assert context.metadata == {}


class TestContextCompressor:
    """Tests for ContextCompressor class."""
    
    @pytest.fixture
    def compressor(self):
        """Create a ContextCompressor instance."""
        return ContextCompressor(max_messages=5, max_tool_result_chars=1000)
    
    @pytest.mark.asyncio
    async def test_compress_within_limits(self, compressor):
        """Test compression when context is within limits."""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        
        result = await compressor.compress(messages)
        
        assert len(result.compressed_messages) == 3
        assert result.kept_messages_count == 3
        assert result.removed_messages_count == 0
        assert "no compression needed" in result.summary.lower()
    
    @pytest.mark.asyncio
    async def test_compress_exceeds_limits(self, compressor):
        """Test compression when context exceeds limits."""
        messages = []
        for i in range(20):
            messages.append({"role": "user", "content": f"message {i}"})
            messages.append({"role": "assistant", "content": f"response {i}"})
        
        result = await compressor.compress(messages)
        
        assert result.kept_messages_count <= 5 or result.removed_messages_count > 0
        assert result.kept_messages_count + result.removed_messages_count == len(messages) or result.removed_messages_count > 0
    
    @pytest.mark.asyncio
    async def test_compress_with_execution_results(self, compressor):
        """Test compression with execution results."""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "list files"},
        ]
        
        results = [
            ExecutionResult(
                step_index=0,
                step_type=StepType.TOOL_CALL,
                tool_name="list_dir",
                status=ExecutionStatus.SUCCESS,
                success=True,
                output="file1.py\nfile2.py\nfile3.py",
            ),
        ]
        
        result = await compressor.compress(messages, results)
        
        assert "list_dir" in result.compressed_tool_results
    
    def test_summarize_long_output(self, compressor):
        """Test summarizing long tool output."""
        long_output = "\n".join([f"line {i}" for i in range(100)])
        
        summary = compressor._summarize_long_output(long_output, "list_dir")
        
        assert len(summary) < len(long_output)
        assert "[Tool" in summary
        assert "list_dir" in summary
    
    def test_extract_important_keywords(self, compressor):
        """Test extracting important keywords from messages."""
        messages = [
            {"role": "user", "content": "I have an error in my file. Please debug this issue."},
            {"role": "assistant", "content": "Let me check the function and variable."},
        ]
        
        keywords = compressor.extract_important_keywords(messages)
        
        assert isinstance(keywords, list)
        for kw in keywords:
            assert isinstance(kw, str)
    
    @pytest.mark.asyncio
    async def test_compress_empty_history(self, compressor):
        """Test compressing empty conversation history."""
        result = await compressor.compress([])
        
        assert result.compressed_messages == []
        assert result.kept_messages_count == 0
        assert result.removed_messages_count == 0
    
    @pytest.mark.asyncio
    async def test_compress_none_history(self, compressor):
        """Test compressing None conversation history."""
        result = await compressor.compress(None)
        
        assert result.compressed_messages == []
        assert result.kept_messages_count == 0
    
    @pytest.mark.asyncio
    async def test_compress_tool_results(self, compressor):
        """Test compressing individual tool results."""
        results = [
            ExecutionResult(
                step_index=0,
                step_type=StepType.TOOL_CALL,
                tool_name="list_dir",
                status=ExecutionStatus.SUCCESS,
                success=True,
                output="short result",
            ),
            ExecutionResult(
                step_index=1,
                step_type=StepType.TOOL_CALL,
                tool_name="grep",
                status=ExecutionStatus.SUCCESS,
                success=True,
                output="x" * 2000,
            ),
        ]
        
        compressed = compressor._compress_tool_results(results)
        
        assert "list_dir" in compressed
        assert "grep" in compressed
        assert len(compressed["grep"]) < 2000
