"""Tests for system info tool."""

import pytest

from nanobot.agent.tools.system import SystemInfoTool


@pytest.mark.asyncio
async def test_system_info_tool_all() -> None:
    """Test system_info tool with 'all' option."""
    tool = SystemInfoTool()
    result = await tool.execute(info_type="all")
    
    assert "System Information" in result
    assert "OS Information" in result
    assert "CPU Information" in result
    assert "Memory Information" in result
    assert "Disk Information" in result


@pytest.mark.asyncio
async def test_system_info_tool_os() -> None:
    """Test system_info tool with 'os' option."""
    tool = SystemInfoTool()
    result = await tool.execute(info_type="os")
    
    assert "OS Information" in result
    assert "System:" in result


@pytest.mark.asyncio
async def test_system_info_tool_cpu() -> None:
    """Test system_info tool with 'cpu' option."""
    tool = SystemInfoTool()
    result = await tool.execute(info_type="cpu")
    
    assert "CPU Information" in result
    assert "CPU Count" in result


@pytest.mark.asyncio
async def test_system_info_tool_memory() -> None:
    """Test system_info tool with 'memory' option."""
    tool = SystemInfoTool()
    result = await tool.execute(info_type="memory")
    
    assert "Memory Information" in result


@pytest.mark.asyncio
async def test_system_info_tool_disk() -> None:
    """Test system_info tool with 'disk' option."""
    tool = SystemInfoTool()
    result = await tool.execute(info_type="disk")
    
    assert "Disk Information" in result
    assert "Total:" in result
    assert "Used:" in result
    assert "Free:" in result


@pytest.mark.asyncio
async def test_system_info_tool_default() -> None:
    """Test system_info tool with default (no parameter)."""
    tool = SystemInfoTool()
    result = await tool.execute()
    
    assert "System Information" in result


@pytest.mark.asyncio
async def test_system_info_tool_invalid_type() -> None:
    """Test system_info tool with invalid info_type."""
    tool = SystemInfoTool()
    result = await tool.execute(info_type="invalid")
    
    assert "Error" in result
    assert "Unknown info_type" in result


def test_system_info_tool_schema() -> None:
    """Test system_info tool schema."""
    tool = SystemInfoTool()
    schema = tool.to_schema()
    
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "system_info"
    assert "info_type" in schema["function"]["parameters"]["properties"]
    assert "all" in schema["function"]["parameters"]["properties"]["info_type"]["enum"]


def test_system_info_tool_validate_params() -> None:
    """Test system_info tool parameter validation."""
    tool = SystemInfoTool()
    
    # Valid parameters
    errors = tool.validate_params({"info_type": "all"})
    assert errors == []
    
    errors = tool.validate_params({"info_type": "os"})
    assert errors == []
    
    errors = tool.validate_params({})
    assert errors == []
    
    # Invalid enum value
    errors = tool.validate_params({"info_type": "invalid"})
    assert len(errors) > 0
    assert "must be one of" in errors[0]
    
    # Invalid type
    errors = tool.validate_params({"info_type": 123})
    assert len(errors) > 0
    assert "should be string" in errors[0]
