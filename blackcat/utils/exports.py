"""Export utilities for generating documentation from registered tools."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from blackcat.agent.tools.base import Tool


def export_tools_md(tools: dict[str, "Tool"], path: Path) -> None:
    """
    Export registered tools to TOOLS.md file for human reading.

    Args:
        tools: Dictionary of registered tools (name -> Tool)
        path: Path to write TOOLS.md (typically workspace/TOOLS.md)
    """
    lines = [
        "# Available Tools",
        "",
        "This document lists all tools available to blackcat.",
        "Auto-generated from registered tools.",
        "",
    ]

    for tool in tools.values():
        lines.append(f"## {tool.name}")
        lines.append("")
        lines.append(tool.description)
        lines.append("")

        # Parameters
        props = tool.parameters.get("properties", {})
        required = set(tool.parameters.get("required", []))

        if props:
            lines.append("**Parameters:**")
            for name, prop in props.items():
                prop_type = prop.get("type", "any")
                desc = prop.get("description", "")
                req = "(required)" if name in required else "(optional)"
                lines.append(f"- `{name}` ({prop_type}) {req}: {desc}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def export_mcp_tools_md(tools: dict[str, "Tool"], path: Path) -> None:
    """
    Export MCP tools to MCP.md file for human reading.

    Only includes tools from MCP servers (those with server_name property).

    Args:
        tools: Dictionary of registered tools (name -> Tool)
        path: Path to write MCP.md (typically workspace/MCP.md)
    """
    # Group MCP tools by server
    mcp_tools: dict[str, list["Tool"]] = {}
    for tool in tools.values():
        server = getattr(tool, "server_name", None)
        if server:
            if server not in mcp_tools:
                mcp_tools[server] = []
            mcp_tools[server].append(tool)

    if not mcp_tools:
        return

    lines = [
        "# MCP Tools",
        "",
        "This document lists all tools from MCP servers.",
        "Auto-generated from connected MCP servers.",
        "",
    ]

    for server, tool_list in sorted(mcp_tools.items()):
        lines.append(f"## Server: `{server}`")
        lines.append("")
        lines.append(f"_{len(tool_list)} tool(s) available_")
        lines.append("")

        for tool in sorted(tool_list, key=lambda t: t.name):
            original_name = getattr(tool, "original_name", tool.name)
            lines.append(f"### {original_name}")
            lines.append("")
            lines.append(f"**Full name:** `{tool.name}`")
            lines.append("")
            lines.append(tool.description)
            lines.append("")

            # Parameters
            props = tool.parameters.get("properties", {})
            required = set(tool.parameters.get("required", []))

            if props:
                lines.append("**Parameters:**")
                for name, prop in props.items():
                    prop_type = prop.get("type", "any")
                    desc = prop.get("description", "")
                    req = "(required)" if name in required else "(optional)"
                    lines.append(f"- `{name}` ({prop_type}) {req}: {desc}")
                lines.append("")

        lines.append("---")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
