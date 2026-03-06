"""Tests for ToolResultTruncator."""

import pytest

from nanobot.agent.tool_result_truncator import ToolResultTruncator


@pytest.fixture
def truncator():
    """Create a truncator with 500 char limit for testing."""
    return ToolResultTruncator(max_chars=500)


def test_no_truncation_needed(truncator):
    """Test that short content is not truncated."""
    content = "Short content"
    result = truncator.truncate("read_file", content)
    assert result == content


def test_read_file_truncation(truncator):
    """Test read_file truncation keeps head + tail."""
    lines = [f"Line {i}" for i in range(100)]
    content = "\n".join(lines)
    
    result = truncator.truncate("read_file", content)
    
    assert len(result) <= 600  # Allow some overhead for omission message
    assert "Line 0" in result  # Head preserved
    assert "Line 99" in result  # Tail preserved
    assert "omitted" in result.lower()


def test_exec_truncation_with_stderr(truncator):
    """Test exec truncation prioritizes stderr."""
    stderr = "Error: something went wrong\n" * 20
    stdout = "Normal output\n" * 50
    content = f"STDERR:\n{stderr}\n\nSTDOUT:\n{stdout}"
    
    result = truncator.truncate("exec", content)
    
    assert len(result) <= 600
    assert "STDERR:" in result
    assert "Error: something went wrong" in result
    # Stdout should be truncated more aggressively
    assert "omitted" in result.lower() or "truncated" in result.lower()


def test_exec_truncation_stdout_only(truncator):
    """Test exec truncation with only stdout."""
    stdout = "Output line\n" * 100
    
    result = truncator.truncate("exec", stdout)
    
    assert len(result) <= 600
    assert "Output line" in result
    assert "omitted" in result.lower()


def test_web_content_truncation(truncator):
    """Test web content truncation extracts key paragraphs."""
    paragraphs = [
        "This is a meaningful paragraph with lots of content.",
        "Another important paragraph with useful information.",
        "Navigation: Home | About | Contact",  # Low content density
        "Copyright 2024. All rights reserved.",  # Low content density
        "More meaningful content here with actual information.",
    ]
    content = "\n\n".join(paragraphs * 10)  # Make it long
    
    result = truncator.truncate("web_fetch", content)
    
    assert len(result) <= 600
    # Should keep high-density paragraphs (either "meaningful" or "important")
    assert ("meaningful" in result.lower() or "important" in result.lower())
    # May omit low-density paragraphs
    assert "omitted" in result.lower() or len(result) < len(content)


def test_list_dir_truncation(truncator):
    """Test list_dir truncation keeps first N entries."""
    entries = [f"file_{i}.txt" for i in range(100)]
    content = "\n".join(entries)
    
    result = truncator.truncate("list_dir", content)
    
    assert len(result) <= 600
    assert "file_0.txt" in result  # First entry preserved
    assert "more entries" in result.lower()


def test_default_truncation(truncator):
    """Test default truncation for unknown tools."""
    content = "x" * 1000
    
    result = truncator.truncate("unknown_tool", content)
    
    assert len(result) <= 600
    assert result.startswith("x" * 100)  # Prefix preserved
    assert "truncated" in result.lower()


def test_truncate_json(truncator):
    """Test JSON truncation."""
    data = {"key": "value" * 200}
    
    result = truncator.truncate_json("some_tool", data)
    
    # Should return dict (possibly truncated)
    assert isinstance(result, dict)


def test_max_chars_respected():
    """Test that max_chars limit is respected."""
    truncator = ToolResultTruncator(max_chars=100)
    content = "x" * 1000
    
    result = truncator.truncate("read_file", content)
    
    # Allow some overhead for omission message
    assert len(result) <= 150


def test_multiline_read_file():
    """Test read_file with realistic multiline content."""
    content = """def hello():
    print("Hello, world!")

def goodbye():
    print("Goodbye!")

""" * 50  # Make it long
    
    truncator = ToolResultTruncator(max_chars=200)
    result = truncator.truncate("read_file", content)
    
    assert len(result) <= 300  # Allow overhead
    assert "def hello():" in result  # Head preserved
    assert "omitted" in result.lower()


def test_empty_content(truncator):
    """Test truncation of empty content."""
    result = truncator.truncate("read_file", "")
    assert result == ""


def test_web_content_no_paragraphs(truncator):
    """Test web content with no clear paragraph structure."""
    content = "x" * 1000
    
    result = truncator.truncate("web_fetch", content)
    
    assert len(result) <= 600
    assert "truncated" in result.lower()
