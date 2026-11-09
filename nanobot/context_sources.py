"""Compact file-use facts captured at source boundaries, not prompt-retention claims."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
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
    # None means no rebuild; an empty tuple is a rebuilt prompt with no sources.
    system_sources: tuple[PromptSource, ...] | None = None


@dataclass
class SourceCapture:
    sources: list[PromptSource] = field(default_factory=list)
    system_sources: list[PromptSource] | None = None

    def drain(self) -> PromptSourcesEvent:
        event = PromptSourcesEvent(tuple(self.sources), None if self.system_sources is None else tuple(self.system_sources))
        self.sources.clear()
        self.system_sources = None
        return event

    def drain_system(self) -> PromptSourcesEvent | None:
        if self.system_sources is None:
            return None
        event = PromptSourcesEvent((), tuple(self.system_sources))
        self.system_sources = None
        return event


_sources: ContextVar[SourceCapture | None] = ContextVar("context_sources", default=None)
_system_source: ContextVar[bool] = ContextVar("context_system_source", default=False)


@contextmanager
def capture_sources() -> Generator[SourceCapture]:
    """Observe builder reads in one run, including its prompt worker tasks."""
    capture = SourceCapture()
    token = _sources.set(capture)
    try:
        yield capture
    finally:
        _sources.reset(token)


@contextmanager
def without_source_capture() -> Generator[None]:
    """Keep independently scheduled runs from inheriting their parent's capture."""
    token = _sources.set(None)
    try:
        yield
    finally:
        _sources.reset(token)


@contextmanager
def system_source_scope() -> Generator[None]:
    """Capture a replacement snapshot of the system prompt's file sources."""
    if (capture := _sources.get()) is not None:
        # Compaction can rebuild the prompt before a request; keep the latest build.
        capture.system_sources = []
    token = _system_source.set(True)
    try:
        yield
    finally:
        _system_source.reset(token)


def drain_system_sources() -> PromptSourcesEvent | None:
    """Take a committed prompt rebuild without consuming pending turn sources."""
    capture = _sources.get()
    return capture.drain_system() if capture is not None else None


def record_source(path: Path, content: str, *, loaded: bool = True) -> None:
    if (capture := _sources.get()) is not None:
        sources = capture.system_sources if _system_source.get() else capture.sources
        if sources is not None:
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
