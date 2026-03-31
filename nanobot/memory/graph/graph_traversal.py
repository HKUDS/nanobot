"""Traversal algorithms extracted from KnowledgeGraph.

Standalone functions that receive a ``KnowledgeGraph`` instance and perform
multi-hop traversal (BFS path-finding, subgraph merging).
"""

from __future__ import annotations

from collections import deque
from typing import Any

__all__ = ["find_paths", "query_subgraph"]


def find_paths(
    graph: Any,
    source: str,
    target: str,
    max_depth: int = 3,
) -> list[list[dict[str, Any]]]:
    """Find paths between two entities using iterative BFS.

    Returns up to 5 shortest paths.  Each path is a list of edge dicts
    with ``source``, ``relation``, and ``target`` keys (display names).
    """
    from .graph import _norm

    if not graph.enabled or graph._db is None:
        return []
    src = _norm(source)
    tgt = _norm(target)
    max_depth = max(1, min(max_depth, 5))

    if graph._db.get_entity(src) is None or graph._db.get_entity(tgt) is None:
        return []

    # Display-name cache
    _dn: dict[str, str] = {}

    def dn(canonical: str) -> str:
        if canonical not in _dn:
            _dn[canonical] = graph._get_display_name(canonical)
        return _dn[canonical]

    def _edge_rel(n1: str, n2: str) -> str:
        """Find the relation between two adjacent canonical nodes."""
        assert graph._db is not None
        for e in graph._db.get_edges_from(n1):
            if e["target"] == n2:
                return str(e["relation"])
        for e in graph._db.get_edges_from(n2):
            if e["target"] == n1:
                return str(e["relation"])
        return ""

    def _path_to_steps(node_path: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "source": dn(node_path[i]),
                "relation": _edge_rel(node_path[i], node_path[i + 1]),
                "target": dn(node_path[i + 1]),
            }
            for i in range(len(node_path) - 1)
        ]

    queue: deque[list[str]] = deque([[src]])
    paths: list[list[dict[str, Any]]] = []

    while queue and len(paths) < 5:
        path = queue.popleft()
        current = path[-1]
        if len(path) - 1 > max_depth:
            continue

        # Outgoing edges
        for edge in graph._db.get_edges_from(current):
            neighbor = edge["target"]
            if neighbor in path:
                continue
            new_path = path + [neighbor]
            if neighbor == tgt:
                paths.append(_path_to_steps(new_path))
            elif len(new_path) - 1 < max_depth:
                queue.append(new_path)

        # Incoming edges (undirected traversal)
        for edge in graph._db.get_edges_to(current):
            neighbor = edge["source"]
            if neighbor in path:
                continue
            new_path = path + [neighbor]
            if neighbor == tgt:
                paths.append(_path_to_steps(new_path))
            elif len(new_path) - 1 < max_depth:
                queue.append(new_path)

    return paths


async def query_subgraph(
    graph: Any,
    entity_names: list[str],
    depth: int = 1,
) -> dict[str, Any]:
    """Return the merged subgraph around multiple entities.

    Calls ``graph.get_neighbors()`` for each entity and deduplicates
    the resulting nodes and edges.
    """
    if not graph.enabled or not entity_names:
        return {"nodes": [], "edges": []}

    seen_edges: set[tuple[str, str, str]] = set()
    seen_nodes: set[str] = set()
    nodes: list[str] = []
    edges: list[dict[str, Any]] = []

    for name in entity_names:
        edge_list = await graph.get_neighbors(name, depth=depth)
        for edge in edge_list:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            rel = edge.get("relation", "")
            key = (src, rel, tgt)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append(edge)
            for n in (src, tgt):
                if n and n not in seen_nodes:
                    seen_nodes.add(n)
                    nodes.append(n)

    return {"nodes": nodes, "edges": edges}
