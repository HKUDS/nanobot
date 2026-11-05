"""Compact file-use facts captured at source boundaries, not prompt-retention claims."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

from nanobot.events import AgentEvent


class SourceReceipt(TypedDict):
    path: str
    name: str
    tokens: int
    links: list[str]
    loaded: bool


@dataclass(frozen=True)
class PromptSource:
    path: Path
    content: str
    loaded: bool = True


@dataclass(frozen=True)
class PromptSourcesEvent(AgentEvent):
    sources: tuple[PromptSource, ...]


_sources: ContextVar[list[PromptSource] | None] = ContextVar("context_sources", default=None)


@contextmanager
def capture_sources() -> Generator[list[PromptSource]]:
    """Observe builder reads in one run, including its prompt worker tasks."""
    sources: list[PromptSource] = []
    token = _sources.set(sources)
    try:
        yield sources
    finally:
        _sources.reset(token)


def record_source(path: Path, content: str, *, loaded: bool = True) -> None:
    if (sources := _sources.get()) is not None:
        # Keep parsing and token estimation out of prompt construction.
        sources.append(PromptSource(path, content, loaded))


def parse_source_receipt(value: object) -> SourceReceipt | None:
    """Validate one persisted file-read fact at the display history boundary."""
    if not isinstance(value, dict):
        return None
    source = cast(dict[str, object], value)
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
    return {"path": path, "name": name, "tokens": tokens, "links": cast(list[str], links), "loaded": loaded}
