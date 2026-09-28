"""Installed ripgrep with native arguments and shared process controls."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import os
import shutil
from typing import Any

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.shell import ExecTool


class RgTool(ExecTool):
    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        if not ctx.config.file.enable or not super().enabled(ctx):
            return False
        cfg = ctx.config.exec
        path = os.pathsep.join(part for part in (
            cfg.path_prepend, os.environ.get("PATH", ""), cfg.path_append,
        ) if part)
        return shutil.which("rg", path=path) is not None

    @property
    def name(self) -> str:
        return "rg"

    @property
    def description(self) -> str:
        return (
            "Search file contents and discover files with ripgrep. "
            "Accepts native rg arguments as an array of strings."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        schema = super().parameters
        properties = schema["properties"]
        for name in ("command", "cmd", "shell", "login"):
            properties.pop(name, None)
        properties["args"] = {
            "type": "array", "items": {"type": "string"}, "minItems": 1,
            "description": "Native rg arguments, with each argument as one array element",
        }
        schema["required"] = ["args"]
        return schema

    async def execute(self, args: list[str], **kwargs: Any) -> str:
        if not args:
            return ToolResult.error("Error: Provide rg arguments, such as --help or --files.")
        for name in ("command", "cmd", "shell", "login"):
            kwargs.pop(name, None)
        return await super().execute(command=["rg", *args], **kwargs)
