"""Compact file-use facts captured at source boundaries, not prompt-retention claims."""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, TypedDict, cast


class SourceReceipt(TypedDict):
    path: str
    name: str
    tokens: int
    links: list[str]
    loaded: bool


class SourceMetadata(TypedDict):
    context_sources: list[SourceReceipt]


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


def record_source(path: Path, content: str, *, loaded: bool = True) -> None:
    if (sources := _sources.get()) is not None:
        from nanobot.file_references import source_receipt

        sources.append(source_receipt(path, content, loaded=loaded))


def source_metadata(sources: list[SourceReceipt]) -> SourceMetadata:
    return {"context_sources": sources}


def parse_source_metadata(value: object) -> SourceMetadata | None:
    """Validate persisted read facts, independent of later message edits."""
    if not isinstance(value, dict):
        return None
    value = cast(dict[str, object], value)
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
    return {"context_sources": sources} if sources else None


def sources_from_messages(messages: Sequence[Mapping[str, Any]]) -> tuple[SourceReceipt, ...]:
    """Collect file-use records from the current compaction epoch."""
    return tuple(source for message in messages
                 if (metadata := parse_source_metadata(message.get("_meta")))
                 for source in metadata["context_sources"])
