"""Installed ripgrep exposed through the shared exec implementation."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import os
import shutil
from copy import deepcopy
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
            "Supports native rg arguments and shell syntax through exec."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        schema = deepcopy(super().parameters)
        properties = schema["properties"]
        properties.pop("command", None)
        properties.pop("cmd", None)
        properties["args"] = {
            "type": "string", "minLength": 1,
            "description": "Native arguments and shell syntax after rg; quote for the selected exec shell",
        }
        schema["required"] = ["args"]
        return schema

    async def execute(self, args: str, **kwargs: Any) -> str:
        if not args.strip():
            return ToolResult.error("Error: Provide rg arguments, such as --help or --files.")
        kwargs.pop("command", None)
        kwargs.pop("cmd", None)
        return await super().execute(command=f"rg {args}", **kwargs)
