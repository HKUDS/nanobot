import os

from nanobot.agent.tools import mcp as mcp_module


def test_mcp_stdio_errlog_targets_agent_log():
    expected = os.path.expanduser("~/.nanobot/logs/agent.log")
    assert mcp_module._MCP_STDIO_ERRLOG == expected
