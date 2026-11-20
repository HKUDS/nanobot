import asyncio
import threading

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.tools.filesystem import ReadFileTool
from nanobot.context_graph import graph_from_parts, graph_from_sources
from nanobot.context_sources import PromptSource
from nanobot.events import EventSink
from nanobot.file_references import REFERENCE_PARSERS, source_receipt
from nanobot.providers.base import ToolCallRequest
from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
from nanobot.session.manager import SessionManager
from nanobot.webui.context_observer import ContextGraphObserver, read_source
from nanobot.webui.history import fact_from_record

EMPTY = {"nodes": [], "edges": []}


def read_event(path, result, *, call_id="read-1", directory=None):
    return {"name": "read_file", "phase": "end", "call_id": call_id,
            "arguments": {"path": str(path)}, "result": result,
            "working_directory": str(directory) if directory is not None else None}


async def test_observer_uses_only_returned_partial_text(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("[Visible](shown.md)\n[Hidden](unread.md)\n")
    result = await ReadFileTool(workspace=tmp_path).execute(path="guide.md", limit=1)
    path.unlink()  # Observing a result must not depend on today's file contents.
    source = read_source(read_event("guide.md", result, directory=tmp_path))
    assert source["links"] == [str(tmp_path / "shown.md")]
    assert source["tokens"] == source_receipt(path, "[Visible](shown.md)")["tokens"]


async def test_hook_captures_working_directory_at_start(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "loop.py").write_text("print('first')")
    emitted = []

    async def publish(event):
        emitted.append(event)

    monkeypatch.chdir(first)
    hook = AgentProgressHook(EventSink(publish))
    call = ToolCallRequest("read", "read_file", {"path": "loop.py"})
    await hook.on_tool_execution_event(AgentHookContext(0, [], tool_calls=[call]))
    result = await ReadFileTool(workspace=first).execute(path="loop.py")
    monkeypatch.chdir(second)
    await hook.on_tool_execution_event(AgentHookContext(
        0, [], tool_calls=[call], tool_results=[result], tool_events=[{"status": "ok"}],
    ))
    finished = emitted[-1]
    source = read_source(finished.tool_events[0])
    assert source["path"] == str(first / "loop.py")


@pytest.mark.parametrize("prompt", [False, True])
async def test_analysis_runs_off_loop_and_failure_keeps_read_result(tmp_path, monkeypatch, prompt):
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class BrokenParser:
        def references(self, content):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
            raise ValueError("bad parser")

    monkeypatch.setitem(REFERENCE_PARSERS, ".md", BrokenParser())
    path = tmp_path / "guide.md"
    path.write_text("[Guide](other.md)")
    # The tool succeeds before any graph parser runs.
    result = await ReadFileTool(workspace=tmp_path).execute(path=str(path))
    assert "1| [Guide](other.md)" in result
    event = read_event(path, result)
    observer = ContextGraphObserver(None)
    task = asyncio.create_task(
        observer.observe_prompt("chat", (PromptSource(path, "[Guide](other.md)"),), {}, persistent=False)
        if prompt else observer.observe_tools("chat", [event], {}, persistent=False)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert not task.done()
    finally:
        release.set()
    await task
    assert event["result"] == result
    assert await observer.snapshot("chat", {}, persistent=False) == EMPTY


async def test_display_history_restores_reads_and_resets_at_compaction(tmp_path):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = await sessions.state.get("websocket:graph")
    metadata = {HISTORY_GENERATION_METADATA_KEY: session.generation}
    observer = ContextGraphObserver(sessions)

    async def persist(record):
        await sessions.state.append_history(session.key, [fact_from_record(record)], expected_generation=session.generation)

    try:
        event = read_event(tmp_path / "loop.py", "1| print('hello')\n\n(End of file — 1 lines total)")
        await observer.observe_tools("graph", [event], metadata, persistent=True)
        await persist({"event": "message", "kind": "progress", "tool_events": [event]})
        # A read is recoverable even if the run stops before the next model request.
        observer = ContextGraphObserver(sessions)
        initial = graph_from_sources([source_receipt(tmp_path / "SOUL.md", "Be precise")])
        await observer.observe_prompt("graph", (PromptSource(tmp_path / "SOUL.md", "Be precise"),), metadata, persistent=True)
        graph = await observer.snapshot("graph", metadata, persistent=True)
        assert {node["name"] for node in graph["nodes"]} == {"loop.py", "SOUL.md"}
        await persist({"event": "model_request", "context_graph": graph})
        # Repeated initial sources and a process restart do not inflate estimates.
        observer = ContextGraphObserver(sessions)
        assert await observer.snapshot("graph", metadata, persistent=True) == graph
        await observer.reset("graph", metadata, persistent=True)
        await persist({"event": "context_compaction", "phase": "succeeded", "compaction_id": "compact"})
        observer = ContextGraphObserver(sessions)
        await observer.observe_prompt("graph", (PromptSource(tmp_path / "SOUL.md", "Be precise"),), metadata, persistent=True)
        assert await observer.snapshot("graph", metadata, persistent=True) == initial
    finally:
        await sessions.state.aclose()


async def test_partial_reads_deduplicate_calls_and_isolate_chats(tmp_path):
    observer = ContextGraphObserver(None)
    first = read_event(tmp_path / "loop.py", "1| first", call_id="a")
    second = read_event(tmp_path / "loop.py", "2| second", call_id="b")
    await observer.observe_tools("one", [first, first, second], {}, persistent=False)
    graph = await observer.snapshot("one", {}, persistent=False)
    assert graph["nodes"][0]["tokens"] == first["context_source"]["tokens"] + second["context_source"]["tokens"]
    assert await observer.snapshot("two", {}, persistent=False) == EMPTY
    observer.discard("one")
    assert await observer.snapshot("one", {}, persistent=False) == EMPTY


@pytest.mark.parametrize("result,phase", [
    ("[File unchanged since last read: guide.md]", "end"),
    ("Error: File not found: guide.md", "error"),
])
async def test_non_read_results_keep_existing_graph(tmp_path, result, phase):
    observer = ContextGraphObserver(None)
    initial = graph_from_sources([source_receipt(tmp_path / "guide.md", "Original")])
    await observer.observe_prompt("chat", (PromptSource(tmp_path / "guide.md", "Original"),), {}, persistent=False)
    event = {**read_event(tmp_path / "guide.md", result), "phase": phase}
    await observer.observe_tools("chat", [event], {}, persistent=False)
    assert await observer.snapshot("chat", {}, persistent=False) == initial


async def test_prompt_rebuild_deduplicates_files_and_compaction_refreshes_sources(tmp_path):
    observer = ContextGraphObserver(None)
    source = PromptSource(tmp_path / "AGENTS.md", "[Rules](rules.md)")
    await observer.observe_prompt("chat", (source, source), {}, persistent=False)
    expected = graph_from_sources([source_receipt(source.path, source.content)])
    assert await observer.snapshot("chat", {}, persistent=False) == expected
    await observer.observe_prompt("chat", (source,), {}, persistent=False)
    assert await observer.snapshot("chat", {}, persistent=False) == expected
    await observer.reset("chat", {}, persistent=False)
    refreshed = PromptSource(source.path, "[New rules](new.md)")
    await observer.observe_prompt("chat", (refreshed,), {}, persistent=False)
    assert await observer.snapshot("chat", {}, persistent=False) == graph_from_sources([
        source_receipt(refreshed.path, refreshed.content),
    ])


async def test_compaction_reuses_only_the_active_turns_system_sources(tmp_path):
    observer = ContextGraphObserver(None)
    first = {"webui_turn_id": "first"}
    second = {"webui_turn_id": "second"}
    soul = tmp_path / "SOUL.md"
    await observer.observe_prompt("chat", (), first, persistent=False,
                                  system_sources=(PromptSource(soul, "[Old](old.md)"),))
    await observer.snapshot("chat", first, persistent=False)
    parts = await observer.reset("chat", first, persistent=False)
    assert parts is not None
    assert {node["name"] for node in graph_from_parts(parts)["nodes"]} == {"SOUL.md", "old.md"}

    await observer.observe_prompt("chat", (), second, persistent=False,
                                  system_sources=(PromptSource(soul, "[New](new.md)"),))
    graph = await observer.snapshot("chat", second, persistent=False)
    assert {node["name"] for node in graph["nodes"]} == {"SOUL.md", "new.md"}
    parts = await observer.reset("chat", second, persistent=False)
    assert parts is not None
    assert {node["name"] for node in graph_from_parts(parts)["nodes"]} == {"SOUL.md", "new.md"}
    assert await observer.snapshot("other-chat", second, persistent=False) == EMPTY


async def test_reading_a_system_file_adds_its_read_tokens_once(tmp_path):
    observer = ContextGraphObserver(None)
    metadata = {"webui_turn_id": "turn"}
    path = tmp_path / "SOUL.md"
    prompt = "Be precise in all responses."
    await observer.observe_prompt("chat", (), metadata, persistent=False,
                                  system_sources=(PromptSource(path, prompt),))
    event = read_event(path, "1| Additional instructions", call_id="read")
    await observer.observe_tools("chat", [event, event], metadata, persistent=False)
    expected = source_receipt(path, prompt)["tokens"] + event["context_source"]["tokens"]
    first = await observer.snapshot("chat", metadata, persistent=False)
    assert first["nodes"][0]["tokens"] == expected
    assert await observer.snapshot("chat", metadata, persistent=False) == first
