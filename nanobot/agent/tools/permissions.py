"""Tool permission management for authorization layer.

Controls which tools auto-execute vs return proposals for user approval.
"""

from __future__ import annotations

import json
from typing import Any


class ToolPermissionManager:
    """Determines whether a tool should auto-approve or require user approval.

    Tools listed in require_approval_tools return proposals instead of executing.
    User overrides take precedence over template defaults.
    Tools NOT in require_approval_tools always auto-approve.
    """

    def __init__(
        self,
        require_approval_tools: set[str],
        user_overrides: dict[str, str] | None = None,
    ):
        self._require_approval = require_approval_tools
        self._user_overrides = user_overrides or {}

    def should_auto_approve(self, tool_name: str) -> bool:
        """Return True if the tool should execute automatically.

        Logic:
        1. If user has an override for this tool, use that.
        2. If tool is in require_approval set, return False.
        3. Otherwise, auto-approve.
        """
        override = self._user_overrides.get(tool_name)
        if override is not None:
            return override == "auto_approved"

        return tool_name not in self._require_approval

    @staticmethod
    def make_proposal(tool_name: str, arguments: dict[str, Any]) -> str:
        """Build the JSON string returned as a tool result for proposed actions."""
        return json.dumps(
            {
                "status": "proposed",
                "tool": tool_name,
                "arguments": arguments,
                "message": "This action requires user approval before execution.",
            },
            ensure_ascii=False,
        )
