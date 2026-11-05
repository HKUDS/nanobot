"""Self-contained graph values for history facts; encoding runs in the storage worker."""
from __future__ import annotations

import base64
import json
import zlib
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, cast

from nanobot.context_graph import (
    ContextEdge,
    ContextGraph,
    ContextNode,
    ContextSnapshot,
    parse_context_graph,
)

_PREFIX = "graph-columns-v1:"
_MAX_BYTES = 8 * 1024 * 1024
_CACHEABLE_BYTES = 128 * 1024


@lru_cache(maxsize=16)
def _compress_small(serialized: str) -> str | None:
    return _compress(serialized)


def _compress(serialized: str) -> str | None:
    graph = parse_context_graph(json.loads(serialized))
    if graph is None:
        return None
    paths = {node["path"]: index for index, node in enumerate(graph["nodes"])}
    columns = [
        [[node["path"], node["name"], node["tokens"], node["state"]] for node in graph["nodes"]],
        [index for edge in graph["edges"] for index in (paths[edge["source"]], paths[edge["target"]])],
    ]
    raw = json.dumps(columns, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"{_PREFIX}{len(serialized.encode('utf-8'))}:{len(raw)}:" + base64.b64encode(zlib.compress(raw, level=1)).decode("ascii")


def encode_graph(value: object) -> object:
    if not isinstance(value, dict):
        return value
    value = cast(dict[str, object], value)
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    size = len(serialized.encode("utf-8"))
    if size > _MAX_BYTES:
        raise ValueError("history graph exceeds the 8 MiB storage limit")
    encoded = _compress_small(serialized) if size <= _CACHEABLE_BYTES else _compress(serialized)
    return encoded if encoded is not None else value


def encode_graph_fields(content: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(content)
    if "context_graph" in result:
        result["context_graph"] = encode_graph(result["context_graph"])
    snapshot = result.get("context_snapshot")
    if isinstance(snapshot, dict) and "graph" in snapshot:
        snapshot = cast(dict[str, Any], snapshot)
        result["context_snapshot"] = {**snapshot, "graph": encode_graph(snapshot["graph"])}
    return result


class GraphDecoder:
    """One projection owns validated shared entities, including changing snapshots."""
    def __init__(self) -> None:
        self.graphs: dict[str, ContextGraph | None] = {}
        self.nodes: dict[tuple[object, ...], ContextNode] = {}
        self.edges: dict[tuple[object, object], ContextEdge] = {}
        self.sizes: dict[int, int] = {}

    def node(self, path: object, name: object, tokens: object, state: object) -> ContextNode | None:
        key = (path, name, type(tokens), tokens, state)
        try:
            cached = self.nodes.get(key)
        except TypeError:
            return None
        if cached is not None:
            return cached
        if not isinstance(path, str) or not isinstance(name, str) or type(tokens) is not int or tokens < 0 or state not in ("loaded", "discovered"):
            return None
        node: ContextNode = {"path": path, "name": name, "tokens": tokens,
                             "state": "loaded" if state == "loaded" else "discovered"}
        self.nodes[key] = node
        self.sizes[id(node)] = len(json.dumps(node, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return node

    def edge(self, source: str, target: str) -> ContextEdge:
        key = (source, target)
        if key not in self.edges:
            edge: ContextEdge = {"source": source, "target": target}
            self.edges[key] = edge
            self.sizes[id(edge)] = len(json.dumps(edge, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return self.edges[key]

    def inline(self, value: object) -> ContextGraph | None:
        if not isinstance(value, dict):
            return None
        value = cast(dict[str, object], value)
        raw_nodes, raw_edges = value.get("nodes"), value.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            return None
        nodes: list[ContextNode] = []
        for raw in cast(list[object], raw_nodes):
            if not isinstance(raw, dict):
                return None
            row = cast(dict[str, object], raw)
            node = self.node(row.get("path"), row.get("name"), row.get("tokens"), row.get("state"))
            if node is None:
                return None
            nodes.append(node)
        paths = {node["path"] for node in nodes}
        edges: list[ContextEdge] = []
        for raw in cast(list[object], raw_edges):
            if not isinstance(raw, dict):
                return None
            row = cast(dict[str, object], raw)
            source, target = row.get("source"), row.get("target")
            if not isinstance(source, str) or not isinstance(target, str) or source not in paths or target not in paths:
                return None
            edges.append(self.edge(source, target))
        return {"nodes": nodes, "edges": edges}

    def columns(self, value: object, logical_bytes: int) -> ContextGraph | None:
        if not isinstance(value, list) or len(cast(list[object], value)) != 2:
            return None
        rows, indices = cast(list[object], value)
        if not isinstance(rows, list) or not isinstance(indices, list) or len(cast(list[object], indices)) % 2:
            return None
        nodes: list[ContextNode] = []
        for row in cast(list[object], rows):
            if not isinstance(row, list) or len(cast(list[object], row)) != 4:
                return None
            path, name, tokens, state = cast(list[object], row)
            node = self.node(path, name, tokens, state)
            if node is None:
                return None
            nodes.append(node)
        indices = cast(list[object], indices)
        if any(type(index) is not int or not 0 <= index < len(nodes) for index in indices):
            return None
        positions = cast(list[int], indices)
        edges = [self.edge(nodes[positions[i]]["path"], nodes[positions[i + 1]]["path"])
                 for i in range(0, len(positions), 2)]
        # Do not trust a small declared logical size to bypass the replay byte budget.
        size = 23 + max(0, len(nodes) - 1) + max(0, len(edges) - 1)
        size += sum(self.sizes[id(node)] for node in nodes) + sum(self.sizes[id(edge)] for edge in edges)
        return {"nodes": nodes, "edges": edges} if size <= logical_bytes else None

    def graph(self, value: object) -> ContextGraph | None:
        if isinstance(value, str):
            key = value
        elif isinstance(value, dict):
            try:
                key = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            except (ValueError, TypeError):
                return None
        else:
            return None
        if key in self.graphs:
            return self.graphs[key]
        self.graphs[key] = None
        if isinstance(value, str):
            if not value.startswith(_PREFIX) or len(value) > _MAX_BYTES * 2:
                return None
            try:
                logical_text, size_text, encoded = value[len(_PREFIX):].split(":", 2)
                logical_size, size = int(logical_text), int(size_text)
                if not 0 <= logical_size <= _MAX_BYTES or not 0 <= size <= _MAX_BYTES:
                    return None
                raw = base64.b64decode(encoded, validate=True)
                inflater = zlib.decompressobj()
                expanded = inflater.decompress(raw, _MAX_BYTES + 1)
                if len(expanded) != size or not inflater.eof or inflater.unused_data:
                    return None
                graph = self.columns(json.loads(expanded), logical_size)
            except (ValueError, zlib.error, UnicodeDecodeError):
                return None
        else:
            graph = self.inline(cast(object, value))
        self.graphs[key] = graph
        return graph


_decoder: ContextVar[GraphDecoder | None] = ContextVar("history_graph_decoder", default=None)


@contextmanager
def graph_decoding() -> Generator[None]:
    token = _decoder.set(GraphDecoder())
    try:
        yield
    finally:
        _decoder.reset(token)


def decode_graph(value: object) -> ContextGraph | None:
    return (_decoder.get() or GraphDecoder()).graph(value)


def decode_snapshot(value: object) -> ContextSnapshot | None:
    if not isinstance(value, dict):
        return None
    snapshot = cast(dict[str, object], value)
    tokens, window = snapshot.get("estimated_tokens"), snapshot.get("context_window_tokens")
    if type(tokens) is not int or tokens < 0 or type(window) is not int or window <= 0:
        return None
    graph = decode_graph(snapshot.get("graph"))
    return {"graph": graph, "estimated_tokens": tokens, "context_window_tokens": window} if graph is not None else None


def expand_graph_fields(content: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(content)
    for field, decode in (("context_graph", decode_graph), ("context_snapshot", decode_snapshot)):
        if field in result:
            decoded = decode(result[field])
            if decoded is None:
                result.pop(field)
            else:
                result[field] = decoded
    return result


def graph_size_adjustment(content: Mapping[str, Any]) -> int:
    """Retain the original replay byte budget despite storage compression."""
    values = [content.get("context_graph")]
    snapshot = content.get("context_snapshot")
    if isinstance(snapshot, dict):
        values.append(cast(dict[str, object], snapshot).get("graph"))
    adjustment = 0
    for value in values:
        if isinstance(value, str) and value.startswith(_PREFIX):
            try:
                size = int(value[len(_PREFIX):].split(":", 1)[0])
            except ValueError:
                continue
            if 0 <= size <= _MAX_BYTES:
                adjustment += size - len(value) - 2  # ASCII encoding plus JSON quotes.
    return adjustment


def history_record_size(record: str) -> int:
    stored = len(record.encode("utf-8"))
    if '"uncompressed_bytes":' not in record:
        return stored
    value = json.loads(record).get("uncompressed_bytes")
    return value if type(value) is int and 0 <= value <= _MAX_BYTES else stored
