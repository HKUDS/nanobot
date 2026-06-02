"""Task canvas: rule-generated Mermaid graph from node registry."""

from __future__ import annotations

import re
from pathlib import Path

from nanobot.agent.layered_memory.offload.node_registry import MemoryNode, NodeRegistry
from nanobot.utils.helpers import _write_text_atomic

_CANVAS_FILE = "canvas.mmd"
_MERMAID_UNSAFE = re.compile(r'["\[\]#;]')
_WHITESPACE = re.compile(r"\s+")


def _escape_mermaid_label(text: str, *, max_len: int = 80) -> str:
    line = _WHITESPACE.sub(" ", text.strip())
    if len(line) > max_len:
        line = line[: max_len - 3] + "..."
    return _MERMAID_UNSAFE.sub(" ", line)


def build_mermaid_from_nodes(nodes: list[MemoryNode]) -> str:
    """Build a simple ``graph TD`` chain ordered by ``ts`` (v1 rules, no LLM)."""
    if not nodes:
        return ""
    ordered = sorted(nodes, key=lambda n: n.ts)
    lines = ["graph TD"]
    mermaid_ids: list[str] = []
    for index, node in enumerate(ordered):
        node_id = f"n{index}"
        mermaid_ids.append(node_id)
        label = _escape_mermaid_label(f"{node.tool}: {node.summary or node.tool}")
        lines.append(f'    {node_id}["{label}"]')
    for index in range(len(mermaid_ids) - 1):
        lines.append(f"    {mermaid_ids[index]} --> {mermaid_ids[index + 1]}")
    return "\n".join(lines)


def format_node_index(nodes: list[MemoryNode], *, max_entries: int = 16) -> str:
    """Compact node_id index for runtime (newest first)."""
    if not nodes:
        return ""
    ordered = sorted(nodes, key=lambda n: n.ts, reverse=True)[:max_entries]
    entries = ", ".join(f"{node.node_id} ({node.tool})" for node in ordered)
    suffix = "" if len(nodes) <= max_entries else f" … +{len(nodes) - max_entries} more"
    return f"Nodes: {entries}{suffix}"


def format_canvas_runtime_lines(
    mmd: str,
    nodes: list[MemoryNode],
    *,
    max_chars: int,
    max_index_entries: int = 16,
) -> list[str]:
    """Lines injected into ``current_runtime_lines`` (before char budget trim)."""
    if not mmd.strip() and not nodes:
        return []
    lines = ["[Task canvas]"]
    if mmd.strip():
        lines.extend(["```mermaid", mmd.strip(), "```"])
    index_line = format_node_index(nodes, max_entries=max_index_entries)
    if index_line:
        lines.append(index_line)
    return truncate_canvas_lines(lines, max_chars=max_chars)


def truncate_canvas_lines(lines: list[str], *, max_chars: int) -> list[str]:
    """Trim canvas block to ``max_canvas_chars`` (whole joined text)."""
    if max_chars <= 0:
        return []
    joined = "\n".join(lines)
    if len(joined) <= max_chars:
        return lines
    if len(lines) <= 1:
        return [joined[:max_chars]]
    # Drop index first, then shrink mermaid body, keep header.
    trimmed = list(lines)
    while len(trimmed) > 1 and len("\n".join(trimmed)) > max_chars:
        trimmed.pop()
    joined = "\n".join(trimmed)
    if len(joined) <= max_chars:
        return trimmed
    header = trimmed[0]
    body = "\n".join(trimmed[1:])
    budget = max_chars - len(header) - 1
    if budget <= 0:
        return [header[:max_chars]]
    if len(body) > budget:
        body = body[: budget - 3] + "..."
    return [header, body] if body else [header[:max_chars]]


class TaskCanvas:
    """Read/write ``canvas.mmd`` beside ``nodes.json`` for one session."""

    def __init__(
        self,
        workspace: Path,
        session_key: str,
        *,
        max_summary_chars: int = 120,
    ) -> None:
        self._registry = NodeRegistry(
            workspace,
            session_key,
            max_summary_chars=max_summary_chars,
        )

    @property
    def registry(self) -> NodeRegistry:
        return self._registry

    @property
    def mmd_path(self) -> Path:
        return self._registry.session_dir / _CANVAS_FILE

    def refresh(self) -> str:
        """Regenerate ``canvas.mmd`` from ``nodes.json``."""
        mmd = build_mermaid_from_nodes(self._registry.list_nodes())
        if mmd:
            _write_text_atomic(self.mmd_path, mmd)
        elif self.mmd_path.exists():
            self.mmd_path.unlink(missing_ok=True)
        return mmd

    def read(self, *, refresh: bool = False) -> str:
        if refresh or not self.mmd_path.exists():
            return self.refresh()
        return self.mmd_path.read_text(encoding="utf-8")

    def runtime_lines(self, *, max_chars: int) -> list[str]:
        """Refresh graph and return truncated runtime lines."""
        mmd = self.refresh()
        nodes = self._registry.list_nodes()
        return format_canvas_runtime_lines(mmd, nodes, max_chars=max_chars)
