"""Per-session tool result node registry (``nodes.json``)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import _write_text_atomic, ensure_dir

_CANVAS_DIR = ".nanobot/canvas"
_NODES_FILE = "nodes.json"


@dataclass(frozen=True)
class MemoryNode:
    node_id: str
    tool: str
    path: str | None
    summary: str
    chars: int
    ts: float


class NodeRegistry:
    """Read/write ``{workspace}/.nanobot/canvas/{session}/nodes.json``."""

    def __init__(
        self,
        workspace: Path,
        session_key: str,
        *,
        max_summary_chars: int = 120,
    ) -> None:
        self._workspace = workspace
        self._session_key = session_key
        self._max_summary_chars = max(20, max_summary_chars)
        safe = SessionManager.safe_key(session_key or "default")
        self._session_dir = ensure_dir(workspace / _CANVAS_DIR / safe)

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    @property
    def nodes_path(self) -> Path:
        return self._session_dir / _NODES_FILE

    def list_nodes(self) -> list[MemoryNode]:
        return self._load_all()

    def get(self, node_id: str) -> MemoryNode | None:
        for node in self._load_all():
            if node.node_id == node_id:
                return node
        return None

    def upsert(
        self,
        *,
        node_id: str,
        tool: str,
        path: str | None,
        summary: str,
        chars: int,
    ) -> MemoryNode:
        """Insert or update a node by ``node_id``."""
        nodes = self._load_all()
        now = time.time()
        clipped_summary = summarize_tool_result(summary or tool, max_chars=self._max_summary_chars)
        updated = MemoryNode(
            node_id=node_id,
            tool=tool,
            path=path,
            summary=clipped_summary,
            chars=max(0, chars),
            ts=now,
        )
        replaced = False
        for idx, node in enumerate(nodes):
            if node.node_id == node_id:
                nodes[idx] = updated
                replaced = True
                break
        if not replaced:
            nodes.append(updated)
        self._save_all(nodes)
        logger.debug(
            "layered_memory node_registered tool={} node_id={} chars={} path={}",
            tool,
            node_id,
            chars,
            path or "-",
        )
        return updated

    def _load_all(self) -> list[MemoryNode]:
        path = self.nodes_path
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to read {}", path)
            return []
        if not isinstance(raw, list):
            return []
        nodes: list[MemoryNode] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            node = _parse_node(item)
            if node is not None:
                nodes.append(node)
        return nodes

    def _save_all(self, nodes: list[MemoryNode]) -> None:
        payload = [asdict(node) for node in nodes]
        _write_text_atomic(self.nodes_path, json.dumps(payload, ensure_ascii=False, indent=2))


def summarize_tool_result(text: str, *, max_chars: int) -> str:
    """One-line summary for canvas index (rules-only, no LLM)."""
    line = " ".join(text.strip().split())
    if not line:
        return ""
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 3] + "..."


def tool_result_char_len(content: Any) -> int:
    """Best-effort character count before persist/truncate."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        from nanobot.utils.helpers import stringify_text_blocks

        text = stringify_text_blocks(content)
        return len(text) if text is not None else 0
    if content is None:
        return 0
    return len(str(content))


def format_missing_node_hint(
    registry: NodeRegistry,
    node_id: str,
    *,
    recent_limit: int = 8,
) -> str:
    """Build a friendly error when ``node_id`` is unknown or has no persisted body."""
    nodes = sorted(registry.list_nodes(), key=lambda n: n.ts, reverse=True)
    if not nodes:
        return (
            f"Error: node_id {node_id!r} not found (no tool nodes registered for this session yet). "
            "Run tools first; large outputs are registered automatically when layered memory offload is enabled."
        )
    entries = ", ".join(f"{n.node_id} ({n.tool})" for n in nodes[:recent_limit])
    suffix = "" if len(nodes) <= recent_limit else f" … +{len(nodes) - recent_limit} more"
    return (
        f"Error: node_id {node_id!r} not found. "
        f"Recent nodes: {entries}{suffix}. "
        "Use a node_id from the Task canvas index or from [tool output persisted] lines."
    )


def _parse_node(item: dict[str, Any]) -> MemoryNode | None:
    node_id = item.get("node_id")
    tool = item.get("tool")
    if not node_id or not tool:
        return None
    path = item.get("path")
    summary = item.get("summary")
    if not isinstance(summary, str):
        summary = str(tool)
    try:
        chars = int(item.get("chars", 0))
    except (TypeError, ValueError):
        chars = 0
    try:
        ts = float(item.get("ts", 0.0))
    except (TypeError, ValueError):
        ts = 0.0
    return MemoryNode(
        node_id=str(node_id),
        tool=str(tool),
        path=str(path) if path else None,
        summary=summary,
        chars=chars,
        ts=ts,
    )
