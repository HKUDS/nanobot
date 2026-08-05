"""Agent access to the project terminal shared with the WebUI."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.security.workspace_access import WorkspaceScope, current_workspace_scope
from nanobot.terminal.runtime import (
    TRUSTED_TERMINAL_REQUEST_METADATA_KEY,
    TerminalError,
    TerminalSessionManager,
)


def current_trusted_terminal_scope() -> WorkspaceScope | None:
    """Return server-authorized shared-terminal scope for the active tool call."""
    request = current_request_context()
    scope = current_workspace_scope()
    if (
        request is None
        or request.channel != "websocket"
        or request.metadata.get(TRUSTED_TERMINAL_REQUEST_METADATA_KEY) is not True
        or scope is None
        or scope.access_mode != "full"
    ):
        return None
    return scope


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Terminal operation to perform.",
            enum=["open", "list", "write", "read", "close"],
        ),
        terminal_id=StringSchema(
            "Terminal ID returned by open or list; required for write, read, and close."
        ),
        input=StringSchema("Raw input to write when action is write."),
        enter=BooleanSchema(
            description="Append the terminal Enter key after input (default true).",
            default=True,
            nullable=True,
        ),
        after_seq=IntegerSchema(
            description="For read, return output newer than this cursor. Omit to replay retained output.",
            minimum=0,
            nullable=True,
        ),
        wait_ms=IntegerSchema(
            description="For read/write, wait this long for new output (default 1000ms, max 30000ms).",
            minimum=0,
            maximum=30_000,
            nullable=True,
        ),
        rows=IntegerSchema(
            description="Requested terminal rows when opening.",
            minimum=2,
            maximum=200,
            nullable=True,
        ),
        cols=IntegerSchema(
            description="Requested terminal columns when opening.",
            minimum=2,
            maximum=500,
            nullable=True,
        ),
        required=["action"],
    )
)
class TerminalTool(Tool):
    """Operate the persistent PTY attached to the active WebUI project."""

    config_key = "exec"

    def __init__(self, manager: TerminalSessionManager) -> None:
        self._manager = manager

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        exec_config = getattr(ctx.config, "exec", None)
        return (
            ctx.terminal_session_manager is not None
            and bool(getattr(exec_config, "enable", False))
            # Interactive input cannot safely enforce per-command regexes or
            # the one-shot sandbox wrapper. Keep agent PTY access out of those
            # policy configurations instead of offering a bypass.
            and not getattr(exec_config, "sandbox", "")
            and not getattr(exec_config, "allow_patterns", ())
            and not getattr(exec_config, "deny_patterns", ())
        )

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        if ctx.terminal_session_manager is None:
            raise RuntimeError("TerminalTool requires a terminal session manager")
        return cls(ctx.terminal_session_manager)

    @property
    def name(self) -> str:
        return "terminal"

    @property
    def description(self) -> str:
        return (
            "Operate the persistent interactive terminal shared with the current WebUI project. "
            "Ordinary exec and write_stdin calls already use this visible terminal when compatible; "
            "use terminal for raw keystrokes, ongoing shell state, or direct human-agent "
            "collaboration. Available only for local WebUI chats using Full access."
        )

    @property
    def exclusive(self) -> bool:
        return True

    @staticmethod
    def _project_scope() -> WorkspaceScope | ToolResult:
        request = current_request_context()
        scope = current_workspace_scope()
        if (
            request is None
            or request.channel != "websocket"
            or request.metadata.get(TRUSTED_TERMINAL_REQUEST_METADATA_KEY) is not True
            or scope is None
        ):
            return ToolResult.error(
                "Error: terminal is available only inside a trusted local project-scoped WebUI chat"
            )
        if scope.access_mode != "full":
            return ToolResult.error(
                "Error: terminal requires Full access for the current WebUI project"
            )
        return current_trusted_terminal_scope() or scope

    @staticmethod
    def _require_terminal_id(terminal_id: str | None) -> str | ToolResult:
        value = (terminal_id or "").strip()
        if not value:
            return ToolResult.error("Error: terminal_id is required for this action")
        return value

    async def execute(
        self,
        action: str,
        terminal_id: str | None = None,
        input: str = "",
        enter: bool | None = True,
        after_seq: int | None = None,
        wait_ms: int | None = None,
        rows: int | None = None,
        cols: int | None = None,
    ) -> str:
        scope = self._project_scope()
        if isinstance(scope, ToolResult):
            return scope
        project = Path(scope.project_path)
        try:
            if action == "open":
                info = await self._manager.open(
                    project,
                    rows=rows or 30,
                    cols=cols or 100,
                )
                return json.dumps(asdict(info), ensure_ascii=False)
            if action == "list":
                sessions = await self._manager.list(project)
                return json.dumps([asdict(item) for item in sessions], ensure_ascii=False)

            resolved_id = self._require_terminal_id(terminal_id)
            if isinstance(resolved_id, ToolResult):
                return resolved_id
            if action == "close":
                await self._manager.close(resolved_id, project_path=project)
                return json.dumps({"terminal_id": resolved_id, "closed": True})
            if action == "read":
                result = await self._manager.read(
                    resolved_id,
                    after_seq=after_seq,
                    wait_ms=wait_ms or 0,
                    project_path=project,
                )
                return json.dumps(asdict(result), ensure_ascii=False)
            if action == "write":
                cursor = await self._manager.read(
                    resolved_id,
                    after_seq=2**63 - 1,
                    project_path=project,
                )
                data = input + ("\r" if enter is not False else "")
                if not data:
                    return ToolResult.error("Error: input is required when action='write'")
                await self._manager.write(resolved_id, data, project_path=project)
                result = await self._manager.read(
                    resolved_id,
                    after_seq=cursor.next_seq,
                    wait_ms=1000 if wait_ms is None else wait_ms,
                    project_path=project,
                )
                return json.dumps(asdict(result), ensure_ascii=False)
        except TerminalError as exc:
            return ToolResult.error(f"Error: {exc}")
        return ToolResult.error(f"Error: unknown terminal action: {action}")
