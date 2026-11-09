"""Observe completed reads on the ordered display stream, outside agent execution."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.context_graph import (
    ContextGraph,
    ContextGraphParts,
    graph_from_parts,
    graph_from_sources,
    merge_graph,
)
from nanobot.context_sources import PromptSource, SourceReceipt, parse_source_receipt
from nanobot.file_references import source_receipt
from nanobot.session.display_history import (
    HISTORY_GENERATION_METADATA_KEY,
    HistoryKind,
    HistoryReader,
)
from nanobot.session.history_graph import decode_graph, decode_graph_parts
from nanobot.session.manager import SessionManager
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY
from nanobot.webui.session_identity import webui_session_key


def read_source(event: Mapping[str, Any]) -> SourceReceipt | None:
    """Use only the returned numbered text, never reread a source or link target."""
    if event.get("name") != "read_file" or event.get("phase") != "end":
        return None
    arguments, result = event.get("arguments"), event.get("result")
    if not isinstance(arguments, dict) or not isinstance(result, str):
        return None
    path = cast(dict[str, object], arguments).get("path")
    if not isinstance(path, str) or not path:
        return None
    file = Path(path).expanduser()
    if not file.is_absolute():
        directory = event.get("working_directory")
        if not isinstance(directory, str) or not Path(directory).is_absolute():
            return None
        file = Path(directory) / file
    # ReadFileTool uses numbered lines even for a clipped first line. Its notices
    # and unchanged-file response have no such prefix and must not count twice.
    lines: list[str] = []
    for line in result.splitlines():
        match = re.match(r"^\d+\| ?(.*)$", line)
        if match is None:
            break
        lines.append(match.group(1))
    if not lines:
        return None
    return source_receipt(file, "\n".join(lines))


@dataclass
class _State:
    # Prompt sources and reads belong to the compaction stage; system sources
    # belong to the current turn's prompt and are replaced on each rebuild.
    graph: ContextGraph = field(default_factory=lambda: {"nodes": [], "edges": []})
    reads: ContextGraph = field(default_factory=lambda: {"nodes": [], "edges": []})
    system_graph: ContextGraph = field(default_factory=lambda: {"nodes": [], "edges": []})
    system_turn_id: str | None = None
    calls: set[tuple[str | None, str]] = field(default_factory=set)

    def request_parts(self, turn_id: object) -> ContextGraphParts:
        system: ContextGraph = (
            self.system_graph if isinstance(turn_id, str) and turn_id and turn_id == self.system_turn_id
            else {"nodes": [], "edges": []}
        )
        return {"kind": "context_graph_parts", "stage": self.graph, "system": system, "reads": self.reads}

    def apply(self, event: Mapping[str, Any], turn_id: str | None = None) -> None:
        call_id = event.get("call_id")
        source = parse_source_receipt(event.get("context_source"))
        if not isinstance(call_id, str) or (turn_id, call_id) in self.calls or source is None:
            return
        self.reads = merge_graph(self.reads, graph_from_sources([source]), accumulate=True)
        self.calls.add((turn_id, call_id))


def _restore(history: HistoryReader, generation: str | None) -> _State:
    state = _State()
    revision = history.revision
    if revision is None or generation != revision[0]:
        return state
    pending: list[tuple[Mapping[str, Any], str | None]] = []
    for turn in history.turns(reverse=True):
        for _, fact in reversed(history.read_entries(turn.ordinal)):
            boundary = fact.kind is HistoryKind.COMPACTION and fact.content.get("phase") == "succeeded"
            value = fact.content.get("context_graph")
            parts = decode_graph_parts(value) if fact.kind is HistoryKind.MODEL_REQUEST or boundary else None
            graph = decode_graph(value) if parts is None and (fact.kind is HistoryKind.MODEL_REQUEST or boundary) else None
            if boundary or parts is not None or graph is not None:
                if parts is not None:
                    state.graph = parts["stage"]
                    state.system_graph = parts["system"]
                    state.system_turn_id = fact.turn_id
                    state.reads = parts["reads"]
                elif graph is not None:
                    state.graph = graph
                for event, turn_id in reversed(pending):
                    state.apply(event, turn_id)
                return state
            events = fact.content.get("tool_events")
            if not isinstance(events, list):
                continue
            for event in reversed(cast(list[object], events)):
                if isinstance(event, dict) and "context_source" in event:
                    pending.append((cast(dict[str, Any], event), fact.turn_id))
    for event, turn_id in reversed(pending):
        state.apply(event, turn_id)
    return state


class ContextGraphObserver:
    """Display delivery serializes each chat; other chats have independent state."""

    def __init__(self, sessions: SessionManager | None) -> None:
        self._sessions = sessions
        self._states: dict[tuple[str, str | None], _State] = {}

    def discard(self, chat_id: str) -> None:
        for key in tuple(self._states):
            if key[0] == chat_id:
                del self._states[key]

    async def _state(self, chat_id: str, metadata: Mapping[str, Any], *, persistent: bool) -> _State:
        raw_generation = metadata.get(HISTORY_GENERATION_METADATA_KEY)
        generation = raw_generation if isinstance(raw_generation, str) else None
        key = (chat_id, generation)
        if key not in self._states:
            self.discard(chat_id)
            state = await self._sessions.state.project_history(
                webui_session_key(chat_id), lambda history: _restore(history, generation),
            ) if persistent and self._sessions is not None else _State()
            self._states[key] = state
        return self._states[key]

    async def observe_tools(
        self, chat_id: str, events: list[dict[str, Any]], metadata: Mapping[str, Any], *, persistent: bool,
    ) -> None:
        for event in events:
            if event.get("name") != "read_file" or event.get("phase") != "end":
                continue
            try:
                source = await asyncio.to_thread(read_source, event)
                if source is not None:
                    state = await self._state(chat_id, metadata, persistent=persistent)
                    event["context_source"] = source
                    turn_id = metadata.get(WEBUI_TURN_METADATA_KEY)
                    state.apply(event, turn_id if isinstance(turn_id, str) else None)
            except Exception:
                # A presentation parser failure must not lose the tool result.
                logger.exception("Unable to observe file read for context graph")

    async def observe_prompt(
        self, chat_id: str, sources: tuple[PromptSource, ...], metadata: Mapping[str, Any], *, persistent: bool,
        system_sources: tuple[PromptSource, ...] | None = None,
    ) -> None:
        if not sources and system_sources is None:
            return
        def project() -> tuple[ContextGraph, ContextGraph | None]:
            def graph_for(items: tuple[PromptSource, ...]) -> ContextGraph:
                return graph_from_sources([
                    source_receipt(source.path, source.content, loaded=source.loaded) for source in items
                ])
            return graph_for(sources), graph_for(system_sources) if system_sources is not None else None
        try:
            graph, system_graph = await asyncio.to_thread(project)
            state = await self._state(chat_id, metadata, persistent=persistent)
            if system_graph is not None:
                turn_id = metadata.get(WEBUI_TURN_METADATA_KEY)
                state.system_graph = system_graph
                state.system_turn_id = turn_id if isinstance(turn_id, str) else None
            state.graph = merge_graph(state.graph, graph)
        except Exception:
            logger.exception("Unable to observe prompt sources for context graph")

    async def snapshot_parts(
        self, chat_id: str, metadata: Mapping[str, Any], *, persistent: bool,
    ) -> ContextGraphParts:
        state = await self._state(chat_id, metadata, persistent=persistent)
        return state.request_parts(metadata.get(WEBUI_TURN_METADATA_KEY))

    async def snapshot(
        self, chat_id: str, metadata: Mapping[str, Any], *, persistent: bool,
    ) -> ContextGraph:
        return graph_from_parts(await self.snapshot_parts(chat_id, metadata, persistent=persistent))

    async def reset(
        self, chat_id: str, metadata: Mapping[str, Any], *, persistent: bool,
    ) -> ContextGraphParts | None:
        state = await self._state(chat_id, metadata, persistent=persistent)
        state.graph = {"nodes": [], "edges": []}
        state.reads = {"nodes": [], "edges": []}
        state.calls.clear()
        turn_id = metadata.get(WEBUI_TURN_METADATA_KEY)
        if isinstance(turn_id, str) and turn_id and state.system_turn_id == turn_id:
            return state.request_parts(turn_id)
        return None
