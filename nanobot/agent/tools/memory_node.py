"""Read persisted tool output by layered-memory node_id (tool_call_id)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.layered_memory.offload.node_registry import NodeRegistry, format_missing_node_hint
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.filesystem import ReadFileTool, _FsTool
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        node_id=StringSchema(
            "Tool call id from the Task canvas or [tool output persisted] reference.",
            min_length=1,
        ),
        offset=IntegerSchema(
            1,
            description="Line number to start reading from (1-indexed, default 1)",
            minimum=1,
        ),
        limit=IntegerSchema(
            2000,
            description="Maximum number of lines to read (default 2000)",
            minimum=1,
        ),
        required=["node_id"],
    )
)
class ReadMemoryNodeTool(_FsTool, ContextAware):
    """Resolve a memory node and read its persisted tool output like ``read_file``."""

    _scopes = {"core"}

    def __init__(
        self,
        workspace: Path,
        allowed_dir: Path | None,
        extra_allowed_dirs: list[Path] | None,
        *,
        reader: ReadFileTool,
    ) -> None:
        super().__init__(
            workspace=workspace,
            allowed_dir=allowed_dir,
            extra_allowed_dirs=extra_allowed_dirs,
        )
        self._reader = reader
        self._request_ctx: RequestContext | None = None

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        layered = getattr(ctx, "layered_memory", None)
        if layered is None:
            return False
        return layered.offload_enabled()

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        from nanobot.agent.skills import BUILTIN_SKILLS_DIR

        workspace = Path(ctx.workspace)
        restrict = ctx.config.restrict_to_workspace or ctx.config.exec.sandbox
        allowed_dir = workspace if restrict else None
        extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
        fs_kwargs = {
            "workspace": workspace,
            "allowed_dir": allowed_dir,
            "extra_allowed_dirs": extra_read,
            "file_states": getattr(ctx, "file_state_store", None),
        }
        return cls(
            workspace=workspace,
            allowed_dir=allowed_dir,
            extra_allowed_dirs=extra_read,
            reader=ReadFileTool(**fs_kwargs),
        )

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx = ctx

    @property
    def name(self) -> str:
        return "read_memory_node"

    @property
    def description(self) -> str:
        return (
            "Read the full persisted output for a layered-memory node_id (same as tool_call_id). "
            "Use when the Task canvas or tool message points at a saved file. "
            "Requires layeredMemory offload; only works for outputs that were spilled to disk."
        )

    @property
    def read_only(self) -> bool:
        return True

    def _session_key(self) -> str | None:
        if self._request_ctx is None:
            return None
        if self._request_ctx.session_key:
            return self._request_ctx.session_key
        if self._request_ctx.channel and self._request_ctx.chat_id:
            return f"{self._request_ctx.channel}:{self._request_ctx.chat_id}"
        return None

    async def execute(
        self,
        node_id: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        **kwargs: Any,
    ) -> Any:
        if not node_id or not str(node_id).strip():
            return "Error: node_id is required"

        session_key = self._session_key()
        if not session_key:
            return "Error: no active session context for read_memory_node"

        registry = NodeRegistry(self._workspace, session_key)
        node = registry.get(str(node_id).strip())
        if node is None:
            return format_missing_node_hint(registry, str(node_id).strip())

        if not node.path:
            return (
                f"Error: node_id {node_id!r} ({node.tool}) has no persisted file "
                f"(output was {node.chars} chars, under the spill threshold). "
                f"Summary: {node.summary}"
            )

        try:
            self._resolve(node.path)
        except PermissionError as exc:
            return f"Error: {exc}"

        header = (
            f"[memory node {node_id} | tool={node.tool} | path={node.path}]\n"
        )
        body = await self._reader.execute(
            path=node.path,
            offset=offset,
            limit=limit,
            force=True,
            **kwargs,
        )
        if isinstance(body, str) and body.startswith("Error"):
            return body
        return header + (body if isinstance(body, str) else str(body))
