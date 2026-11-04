"""File provenance for context inspection, kept outside model-visible text."""

from __future__ import annotations

import hashlib
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, cast
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from nanobot.utils.helpers import estimate_message_tokens


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


class SourceReceipt(TypedDict):
    path: str
    name: str
    tokens: int
    links: list[str]
    loaded: bool


class SourceMetadata(TypedDict):
    context_sources: list[SourceReceipt]
    context_source_hash: str


class ReferenceParser(Protocol):
    def references(self, content: str) -> Iterator[str]: ...


class MarkdownReferences:
    def references(self, content: str) -> Iterator[str]:
        for block in MarkdownIt("commonmark").parse(content):
            for token in block.children or ():
                if token.type == "link_open" and (href := token.attrGet("href")):
                    if isinstance(href, str):
                        yield href


REFERENCE_PARSERS: dict[str, ReferenceParser] = {
    ".md": MarkdownReferences(),
    ".markdown": MarkdownReferences(),
}
_sources: ContextVar[list[SourceReceipt] | None] = ContextVar("context_sources", default=None)
CONTEXT_SOURCE_HISTORY_META = "_context_sources"


@contextmanager
def capture_sources() -> Generator[list[SourceReceipt]]:
    sources: list[SourceReceipt] = []
    token = _sources.set(sources)
    try:
        yield sources
    finally:
        _sources.reset(token)


def source_receipt(path: Path, content: str, *, loaded: bool = True) -> SourceReceipt:
    """Discover links without opening, checking, or fetching their targets."""
    path = path.resolve()
    links: list[str] = []
    parser = REFERENCE_PARSERS.get(path.suffix.lower()) if loaded else None
    if parser:
        for href in parser.references(content):
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = str((path.parent / unquote(parsed.path)).resolve())
            if target != str(path) and target not in links:
                links.append(target)
            if len(links) >= 128:
                break
    return {"path": str(path), "name": path.parent.name if path.name == "SKILL.md" else path.name, "tokens": max(0, estimate_message_tokens({"content": content}) - 4) if loaded else 0,
            "links": links, "loaded": loaded}


def record_source(path: Path, content: str, *, loaded: bool = True) -> None:
    if (sources := _sources.get()) is not None:
        sources.append(source_receipt(path, content, loaded=loaded))


def source_metadata(content: str, sources: list[SourceReceipt]) -> SourceMetadata:
    return {"context_sources": sources, "context_source_hash": hashlib.sha256(content.encode()).hexdigest()}


def retained_source_metadata(content: object, value: object) -> SourceMetadata | None:
    """Validate provenance when saving or restoring message history."""
    if not isinstance(content, str) or not isinstance(value, dict):
        return None
    value = cast(dict[str, object], value)
    if value.get("context_source_hash") != hashlib.sha256(content.encode()).hexdigest():
        return None
    raw_sources = value.get("context_sources")
    if not isinstance(raw_sources, list):
        return None
    sources: list[SourceReceipt] = []
    for raw_source in cast(list[object], raw_sources):
        if not isinstance(raw_source, dict):
            return None
        source = cast(dict[str, object], raw_source)
        path, name, tokens = source.get("path"), source.get("name"), source.get("tokens")
        links, loaded = source.get("links"), source.get("loaded")
        if not isinstance(path, str) or not isinstance(name, str):
            return None
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            return None
        if not isinstance(loaded, bool) or not isinstance(links, list):
            return None
        if not all(isinstance(link, str) for link in cast(list[object], links)):
            return None
        sources.append({"path": path, "name": name, "tokens": tokens, "links": cast(list[str], links), "loaded": loaded})
    return source_metadata(content, sources) if sources else None


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


def graph_from_messages(messages: Sequence[Mapping[str, Any]]) -> ContextGraph:
    """Only count receipts whose exact originating content is still retained."""
    nodes: dict[str, ContextNode] = {}
    edges: dict[tuple[str, str], ContextEdge] = {}
    for message in messages:
        meta = retained_source_metadata(message.get("content"), message.get("_meta"))
        if meta is None:
            continue
        for source in meta["context_sources"]:
            path = source["path"]
            node = nodes.setdefault(path, {"path": path, "name": source["name"], "state": "discovered", "tokens": 0})
            if source["loaded"]:
                node["state"] = "loaded"
                node["tokens"] += source["tokens"]
            for target in source["links"]:
                nodes.setdefault(target, {"path": target, "name": Path(target).name, "state": "discovered", "tokens": 0})
                edges[path, target] = {"source": path, "target": target}
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
