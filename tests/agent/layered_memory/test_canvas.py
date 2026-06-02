"""Tests for task canvas Mermaid generation (LM1-B)."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.agent.layered_memory import LayeredMemoryFacade
from nanobot.agent.layered_memory.offload.canvas import (
    TaskCanvas,
    build_mermaid_from_nodes,
    format_canvas_runtime_lines,
    truncate_canvas_lines,
)
from nanobot.agent.layered_memory.offload.node_registry import MemoryNode, NodeRegistry
from nanobot.config.schema import LayeredMemoryConfig


def _node(node_id: str, tool: str, summary: str, ts: float) -> MemoryNode:
    return MemoryNode(
        node_id=node_id,
        tool=tool,
        path=f".nanobot/tool-results/s/{node_id}.txt",
        summary=summary,
        chars=100,
        ts=ts,
    )


def test_build_mermaid_chain_ordered_by_ts() -> None:
    mmd = build_mermaid_from_nodes([
        _node("c2", "grep", "second", 2.0),
        _node("c1", "read_file", "first", 1.0),
    ])
    assert "graph TD" in mmd
    assert 'n0["read_file: first"]' in mmd
    assert 'n1["grep: second"]' in mmd
    assert "n0 --> n1" in mmd


def test_task_canvas_refresh_writes_mmd(tmp_path: Path) -> None:
    registry = NodeRegistry(tmp_path, "sess")
    registry.upsert(
        node_id="call_a",
        tool="list_dir",
        path="out.txt",
        summary="listed workspace",
        chars=50,
    )
    canvas = TaskCanvas(tmp_path, "sess")
    mmd = canvas.refresh()
    assert canvas.mmd_path.exists()
    assert "list_dir" in mmd
    assert canvas.read(refresh=False) == mmd


def test_truncate_canvas_lines_respects_max_chars() -> None:
    long_mmd = build_mermaid_from_nodes([
        _node(f"id{i}", "tool", "x" * 40, float(i)) for i in range(12)
    ])
    nodes = [_node(f"id{i}", "tool", "x" * 40, float(i)) for i in range(12)]
    lines = format_canvas_runtime_lines(long_mmd, nodes, max_chars=400)
    assert lines[0] == "[Task canvas]"
    assert len("\n".join(lines)) <= 400


def test_facade_canvas_lines_empty_when_disabled(tmp_path: Path) -> None:
    facade = LayeredMemoryFacade(tmp_path, LayeredMemoryConfig())
    assert facade.canvas_lines("sess") == []


def test_facade_canvas_lines_with_nodes(tmp_path: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    cfg.offload.max_canvas_chars = 800
    facade = LayeredMemoryFacade(tmp_path, cfg)
    facade.register_tool_result(
        session_key="webui:main",
        node_id="call_1",
        tool_name="read_file",
        persist_path="p.txt",
        summary="read README",
        chars=900,
    )
    facade.register_tool_result(
        session_key="webui:main",
        node_id="call_2",
        tool_name="grep",
        persist_path=None,
        summary="search pattern",
        chars=12,
    )
    lines = facade.canvas_lines("webui:main")
    joined = "\n".join(lines)
    assert "[Task canvas]" in lines[0]
    assert "```mermaid" in joined
    assert "read_file" in joined
    assert "Nodes:" in joined
    assert "call_1" in joined
    assert len(joined) <= 800
    canvas_path = tmp_path / ".nanobot" / "canvas" / "webui_main" / "canvas.mmd"
    assert canvas_path.exists()


def test_refresh_canvas_every_n_tools(tmp_path: Path) -> None:
    cfg = LayeredMemoryConfig(enable=True)
    cfg.offload.enable = True
    cfg.offload.update_canvas_every_n_tools = 2
    facade = LayeredMemoryFacade(tmp_path, cfg)
    for i in range(3):
        facade.register_tool_result(
            session_key="sess",
            node_id=f"call_{i}",
            tool_name="exec",
            persist_path=None,
            summary=f"step {i}",
            chars=10,
        )
    mmd_path = tmp_path / ".nanobot" / "canvas" / "sess" / "canvas.mmd"
    assert mmd_path.exists()
    data = json.loads((tmp_path / ".nanobot" / "canvas" / "sess" / "nodes.json").read_text())
    assert len(data) == 3


def test_truncate_drops_index_before_mermaid() -> None:
    lines = ["[Task canvas]", "```mermaid", "graph TD\n" + "x" * 500, "```", "Nodes: a, b, c"]
    out = truncate_canvas_lines(lines, max_chars=120)
    joined = "\n".join(out)
    assert len(joined) <= 120
    assert out[0] == "[Task canvas]"
