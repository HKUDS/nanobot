"""List tools tool for showing available agent tools."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry


class ListToolsTool(Tool):
    """Tool to list all available tools that the agent can use."""

    def __init__(self, registry: "ToolRegistry"):
        self._registry = registry

    @property
    def name(self) -> str:
        return "list_tools"

    @property
    def description(self) -> str:
        return (
            "List all available tools with their names and descriptions. "
            "Tools are the individual capabilities the agent can use, such as file operations, "
            "web search, running commands, etc. Use this to answer 'what can you do' questions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Optional search term to filter tools by name or description.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category to filter tools by. "
                                   "Categories: file, web, shell, agent, workflow, utility",
                    "enum": ["file", "web", "shell", "agent", "workflow", "utility", "all"],
                },
            },
            "required": [],
        }

    async def execute(
        self,
        search: str | None = None,
        category: str = "all",
        **kwargs: Any,
    ) -> str:
        """List all available tools."""
        tool_names = sorted(self._registry.tool_names)

        # Categorize tools
        categories = {
            "file": ["read_file", "write_file", "edit_file", "list_dir", "multi_edit"],
            "web": ["web_search", "web_fetch", "research"],
            "shell": ["exec"],
            "agent": ["spawn", "list_subagents", "cancel_subagents", "await_agent", "get_agent_result"],
            "workflow": ["parallel_group", "await_group", "spawn_chain", "wait_all"],
            "utility": ["message", "cron", "list_profiles", "list_skills", "list_tools", "todo"],
        }

        # Add browser tools if registered
        all_tools = self._registry.tool_names
        if "camoufox_browser" in all_tools:
            categories["utility"].append("camoufox_browser")

        # Filter by category
        if category != "all":
            tool_names = [t for t in tool_names if t in categories.get(category, [])]

        # Filter by search term
        if search:
            search_lower = search.lower()
            filtered = []
            for name in tool_names:
                tool = self._registry.get(name)
                if tool:
                    if (search_lower in name.lower() or
                        (tool.description and search_lower in tool.description.lower())):
                        filtered.append(name)
            tool_names = filtered

        if not tool_names:
            return "No tools found matching the criteria."

        lines = [f"🔧 Available Tools ({len(tool_names)} total)\n"]

        # Group by category for display
        for cat_name, cat_tools in categories.items():
            cat_tools = [t for t in cat_tools if t in tool_names]
            if not cat_tools:
                continue

            cat_emoji = {
                "file": "📁",
                "web": "🌐",
                "shell": "⚡",
                "agent": "🤖",
                "workflow": "🔄",
                "utility": "🛠️",
            }.get(cat_name, "🔧")

            lines.append(f"## {cat_emoji} {cat_name.title()} Tools")

            for tool_name in cat_tools:
                tool = self._registry.get(tool_name)
                if tool:
                    lines.append(f"**{tool_name}**")
                    if tool.description:
                        # Show first sentence of description
                        desc = tool.description.split('.')[0] + '.'
                        lines.append(f"   {desc}")
            lines.append("")

        # Add tools that don't fit in categories
        uncategorized = [t for t in tool_names if not any(t in cats for cats in categories.values())]
        if uncategorized:
            lines.append("## 🔧 Other Tools")
            for tool_name in uncategorized:
                tool = self._registry.get(tool_name)
                if tool:
                    lines.append(f"**{tool_name}**")
                    if tool.description:
                        desc = tool.description.split('.')[0] + '.'
                        lines.append(f"   {desc}")
            lines.append("")

        return "\n".join(lines)
