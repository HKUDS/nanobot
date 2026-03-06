"""Tests for ToolRanker."""

import pytest

from nanobot.agent.tool_ranker import ToolRanker


@pytest.fixture
def sample_tools():
    """Sample tool definitions in OpenAI format."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a file at the given path",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path to read"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file at the given path",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "The file path to write to"},
                        "content": {"type": "string", "description": "The content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "exec",
                "description": "Execute a shell command and return its output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_github_create_pull_request",
                "description": "Create a new pull request in a GitHub repository",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner"},
                        "repo": {"type": "string", "description": "Repository name"},
                        "title": {"type": "string", "description": "Pull request title"},
                        "head": {"type": "string", "description": "The branch with changes"},
                        "base": {"type": "string", "description": "The branch to merge into"},
                    },
                    "required": ["owner", "repo", "title", "head", "base"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web and return results",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
        },
    ]


def test_rank_tools_github_query(sample_tools):
    """Test ranking tools for a GitHub-related query."""
    ranker = ToolRanker()
    query = "create a GitHub pull request"
    
    ranked = ranker.rank_tools(query, sample_tools, top_k=3)
    
    assert len(ranked) == 3
    # GitHub tool should be ranked first
    assert ranked[0]["function"]["name"] == "mcp_github_create_pull_request"


def test_rank_tools_file_query(sample_tools):
    """Test ranking tools for a file-related query."""
    ranker = ToolRanker()
    query = "read the config file"
    
    ranked = ranker.rank_tools(query, sample_tools, top_k=2)
    
    assert len(ranked) == 2
    # read_file should be ranked first
    assert ranked[0]["function"]["name"] == "read_file"


def test_rank_tools_shell_query(sample_tools):
    """Test ranking tools for a shell command query."""
    ranker = ToolRanker()
    query = "run a shell command to list files"
    
    ranked = ranker.rank_tools(query, sample_tools, top_k=2)
    
    assert len(ranked) == 2
    # exec should be ranked first
    assert ranked[0]["function"]["name"] == "exec"


def test_rank_tools_top_k_zero(sample_tools):
    """Test that top_k=0 returns all tools."""
    ranker = ToolRanker()
    query = "create a GitHub pull request"
    
    ranked = ranker.rank_tools(query, sample_tools, top_k=0)
    
    assert len(ranked) == len(sample_tools)


def test_rank_tools_empty_query(sample_tools):
    """Test that empty query returns all tools."""
    ranker = ToolRanker()
    
    ranked = ranker.rank_tools("", sample_tools, top_k=3)
    
    assert len(ranked) == len(sample_tools)


def test_rank_tools_no_tools():
    """Test ranking with no tools."""
    ranker = ToolRanker()
    
    ranked = ranker.rank_tools("test query", [], top_k=3)
    
    assert len(ranked) == 0


def test_tokenize():
    """Test tokenization."""
    ranker = ToolRanker()
    
    tokens = ranker._tokenize("Create a GitHub pull request")
    
    assert "create" in tokens
    assert "github" in tokens
    assert "pull" in tokens
    assert "request" in tokens
    # Stop words should be filtered
    assert "a" not in tokens


def test_cache_persistence(sample_tools):
    """Test that IDF cache persists across calls."""
    ranker = ToolRanker()
    
    # First call builds cache
    ranker.rank_tools("test query", sample_tools, top_k=3)
    assert len(ranker._idf_cache) > 0
    
    # Second call reuses cache
    cache_size = len(ranker._idf_cache)
    ranker.rank_tools("another query", sample_tools, top_k=3)
    assert len(ranker._idf_cache) == cache_size


def test_clear_cache(sample_tools):
    """Test cache clearing."""
    ranker = ToolRanker()
    
    ranker.rank_tools("test query", sample_tools, top_k=3)
    assert len(ranker._idf_cache) > 0
    assert len(ranker._tool_tokens_cache) > 0
    
    ranker.clear_cache()
    assert len(ranker._idf_cache) == 0
    assert len(ranker._tool_tokens_cache) == 0
