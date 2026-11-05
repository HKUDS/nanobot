"""Client graph projection of file-use facts and persisted snapshot validation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypedDict, cast

from nanobot.context_sources import SourceReceipt


class ContextNode(TypedDict):
    path: str
    name: str
    state: Literal["loaded", "discovered"]
    tokens: int


class ContextEdge(TypedDict):
    source: str
    target: str


class ContextGraph(TypedDict):
    nodes: list[ContextNode]
    edges: list[ContextEdge]


def parse_context_graph(value: object) -> ContextGraph | None:
    """Validate persisted graph data at the transcript boundary."""
    if not isinstance(value, dict):
        return None
    value = cast(dict[str, object], value)
    raw_nodes, raw_edges = value.get("nodes"), value.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return None
    nodes: list[ContextNode] = []
    for raw_node in cast(list[object], raw_nodes):
        if not isinstance(raw_node, dict):
            return None
        node = cast(dict[str, object], raw_node)
        path, name = node.get("path"), node.get("name")
        if not isinstance(path, str) or not isinstance(name, str):
            return None
        tokens, state = node.get("tokens"), node.get("state")
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0 or state not in ("loaded", "discovered"):
            return None
        nodes.append({"path": path, "name": name, "tokens": tokens,
                      "state": "loaded" if state == "loaded" else "discovered"})
    paths = {node["path"] for node in nodes}
    edges: list[ContextEdge] = []
    for raw_edge in cast(list[object], raw_edges):
        if not isinstance(raw_edge, dict):
            return None
        edge = cast(dict[str, object], raw_edge)
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            return None
        if source not in paths or target not in paths:
            return None
        edges.append({"source": source, "target": target})
    return {"nodes": nodes, "edges": edges}


def graph_from_sources(sources: Sequence[SourceReceipt]) -> ContextGraph:
    """Project files used in this epoch, regardless of subsequent text edits."""
    nodes: dict[str, ContextNode] = {}
    edges: dict[tuple[str, str], ContextEdge] = {}
    for source in sources:
        path = source["path"]
        node = nodes.setdefault(path, {"path": path, "name": source["name"], "state": "discovered", "tokens": 0})
        if source["loaded"]:
            node["state"] = "loaded"
            node["tokens"] = max(node["tokens"], source["tokens"])
        for target in source["links"]:
            if target not in nodes:
                nodes[target] = {"path": target, "name": Path(target).name, "state": "discovered", "tokens": 0}
            edges[path, target] = {"source": path, "target": target}
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


class ContextSnapshot(TypedDict):
    graph: ContextGraph
    estimated_tokens: int
    context_window_tokens: int
