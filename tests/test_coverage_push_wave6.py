from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.delegation import _delegation_ancestry
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, ReactionEvent
from nanobot.memory.extractor import MemoryExtractor
from nanobot.memory.graph import KnowledgeGraph
from nanobot.memory.retrieval_planner import RetrievalPlanner
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.tools.base import ToolResult
from tests.test_agent_loop import ScriptedProvider, _make_loop
from tests.test_store_helpers import _store


async def test_loop_process_message_system_help_new_and_conflict_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider([LLMResponse(content="done")])
    loop = _make_loop(tmp_path, provider)

    # system-channel branch
    out = await loop._process_message(
        InboundMessage(channel="system", chat_id="cli:room1", sender_id="sys", content="run now")
    )
    assert out is not None
    assert out.channel == "cli"
    assert out.chat_id == "room1"

    # /help branch
    help_out = await loop._process_message(
        InboundMessage(channel="cli", chat_id="room1", sender_id="u", content="/help")
    )
    assert help_out is not None
    assert "/new" in help_out.content

    # pending conflict branch (before normal loop)
    loop.context.memory.conflict_mgr.ask_user_for_conflict = MagicMock(
        return_value="Please resolve conflict"
    )
    conflict_out = await loop._process_message(
        InboundMessage(channel="cli", chat_id="room1", sender_id="u", content="hello")
    )
    assert conflict_out is not None
    assert "resolve conflict" in conflict_out.content.lower()

    # /new archival failure branch
    key = "cli:room1"
    session = loop.sessions.get_or_create(key)
    session.messages = [
        {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00"},
    ]
    session.last_consolidated = 0

    async def _no_archive(_session, archive_all: bool = False):
        return False

    monkeypatch.setattr(loop._processor, "_consolidate_memory", _no_archive)
    new_out = await loop._process_message(
        InboundMessage(channel="cli", chat_id="room1", sender_id="u", content="/new")
    )
    assert new_out is not None
    assert "failed" in new_out.content.lower()


async def test_loop_new_exception_and_fallback_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider([LLMResponse(content="ok")])
    loop = _make_loop(tmp_path, provider)

    key = "cli:room2"
    session = loop.sessions.get_or_create(key)
    session.messages = [{"role": "user", "content": "snapshot item", "timestamp": "2026-01-01"}]
    session.last_consolidated = 0

    async def _boom(_session, archive_all: bool = False):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(loop._processor, "_consolidate_memory", _boom)

    out = await loop._process_message(
        InboundMessage(channel="cli", chat_id="room2", sender_id="u", content="/new")
    )
    assert out is not None
    assert "failed" in out.content.lower()


def test_graph_entity_helpers_and_disabled_paths() -> None:
    # _node_to_entity invalid enum fallback + extra props
    ent = KnowledgeGraph._node_to_entity(
        {
            "name": "Team Alpha",
            "entity_type": "invalid",
            "aliases_text": "A, B",
            "prop_owner": "carlos",
        }
    )
    assert ent.entity_type.value == "unknown"
    assert ent.properties["owner"] == "carlos"

    graph = KnowledgeGraph()  # no workspace -> disabled

    # Disabled-path guards
    assert graph.get_related_entity_names_sync(set()) == set()
    assert graph.get_triples_for_entities_sync(set()) == []


async def test_extractor_correction_helpers_and_provider_failure() -> None:
    extractor = MemoryExtractor(
        to_str_list=lambda v: [str(x) for x in (v or [])],
        coerce_event=lambda item, source_span: (
            {**item, "source_span": source_span} if isinstance(item, dict) else None
        ),
        utc_now_iso=lambda: "2026-03-11T00:00:00+00:00",
    )

    prefs = extractor.extract_explicit_preference_corrections("I prefer Python but not JavaScript")
    facts = extractor.extract_explicit_fact_corrections(
        "Actually project status is green, not red."
    )
    assert len(prefs) >= 1, "Should extract at least one preference correction"
    assert any("python" in str(p).lower() or "javascript" in str(p).lower() for p in prefs), (
        "Preference correction should reference Python or JavaScript"
    )
    assert len(facts) >= 1, "Should extract at least one fact correction"
    assert any("green" in str(f).lower() or "status" in str(f).lower() for f in facts), (
        "Fact correction should reference project status change"
    )

    class _FailProvider:
        async def chat(self, **_kwargs):
            raise RuntimeError("down")

    events, updates = await extractor.extract_structured_memory(
        _FailProvider(),
        "test-model",
        current_profile={},
        lines=["line"],
        old_messages=[{"role": "user", "content": "I prefer concise output"}],
        source_start=1,
    )
    assert extractor.last_extraction_source == "heuristic"
    assert isinstance(events, list)
    assert "preferences" in updates


async def test_loop_connect_mcp_and_tool_parallel_error_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider([LLMResponse(content="ok")])
    loop = _make_loop(tmp_path, provider)

    loop._mcp_connected = False
    loop._mcp_connecting = False
    loop._mcp_servers = [{"name": "broken"}]

    async def _failing_connect(*_args, **_kwargs):
        raise RuntimeError("mcp boom")

    monkeypatch.setattr("nanobot.tools.builtin.mcp.connect_mcp_servers", _failing_connect)
    await loop._connect_mcp()
    assert loop._mcp_connected is False

    class _ReadonlyTool:
        readonly = True

    class _WriteTool:
        readonly = False

    loop.tools.get = MagicMock(
        side_effect=lambda name: _ReadonlyTool() if name in {"r", "r2"} else _WriteTool()
    )

    async def _execute(name, _arguments):
        if name == "r2":
            raise RuntimeError("tool fail")
        return SimpleNamespace(ok=True)

    loop.tools.execute = AsyncMock(side_effect=_execute)
    calls = [
        SimpleNamespace(name="r", arguments={}),
        SimpleNamespace(name="r2", arguments={}),
        SimpleNamespace(name="w", arguments={}),
    ]
    results = await loop.tools.execute_batch(calls)
    assert len(results) == 3
    assert results[1].success is False


async def test_graph_query_subgraph_dedupe_and_get_entity_none(tmp_path: object) -> None:
    from pathlib import Path

    workspace = Path(str(tmp_path))
    g = KnowledgeGraph(workspace=workspace)

    async def _neighbors(name: str, depth: int = 1, relation_types: list[str] | None = None):
        if name == "a":
            return [{"source": "A", "relation": "REL", "target": "B"}]
        return [
            {"source": "A", "relation": "REL", "target": "B"},
            {"source": "B", "relation": "REL2", "target": "C"},
        ]

    g.get_neighbors = _neighbors  # type: ignore[method-assign]
    sub = await g.query_subgraph(["a", "b"], depth=1)
    assert set(sub["nodes"]) == {"A", "B", "C"}
    assert len(sub["edges"]) == 2

    # get_entity returns None for non-existent entity
    g2 = KnowledgeGraph(workspace=workspace)
    assert await g2.get_entity("Missing") is None


async def test_loop_run_agent_loop_malformed_then_final_nudge(tmp_path: Path) -> None:
    provider = ScriptedProvider([])
    loop = _make_loop(tmp_path, provider)

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[SimpleNamespace(id="t1", name="read_file", arguments={"path": "x"})],
            finish_reason="stop",
        ),
        LLMResponse(
            content=None,
            tool_calls=[SimpleNamespace(id="bad", name="", arguments={})],
            finish_reason="stop",
        ),
        LLMResponse(content="final answer", tool_calls=[], finish_reason="stop"),
    ]

    loop._llm_caller.call = AsyncMock(side_effect=responses)  # type: ignore[method-assign]
    loop.tools.execute_batch = AsyncMock(return_value=[ToolResult.ok("ok")])  # type: ignore[method-assign]

    final, _tools, messages = await loop._run_agent_loop(
        [{"role": "user", "content": "Please do this task."}]
    )
    assert final == "final answer"
    assert any(m.get("role") == "tool" for m in messages)


async def test_loop_run_agent_loop_delegation_and_failure_reflection_paths(
    tmp_path: Path,
) -> None:
    provider = ScriptedProvider([])
    loop = _make_loop(tmp_path, provider)

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[SimpleNamespace(id="d1", name="delegate", arguments={"task": "a"})],
            finish_reason="stop",
        ),
        LLMResponse(content="done", tool_calls=[], finish_reason="stop"),
    ]

    async def _exec(_calls):
        loop._dispatcher.delegation_count = loop._dispatcher.max_delegations
        return [ToolResult.ok("delegated")]

    loop._llm_caller.call = AsyncMock(side_effect=responses)  # type: ignore[method-assign]
    loop.tools.execute_batch = _exec  # type: ignore[method-assign]
    final, _tools, msgs = await loop._run_agent_loop([{"role": "user", "content": "Do A then B."}])
    assert final == "done"
    assert any(
        "Delegation(s) complete" in str(m.get("content", ""))
        for m in msgs
        if m.get("role") == "system"
    )

    responses2 = [
        LLMResponse(
            content=None,
            tool_calls=[SimpleNamespace(id="x1", name="read_file", arguments={"path": "x"})],
            finish_reason="stop",
        ),
        LLMResponse(content="done2", tool_calls=[], finish_reason="stop"),
    ]
    loop._llm_caller.call = AsyncMock(side_effect=responses2)  # type: ignore[method-assign]
    loop.tools.execute_batch = AsyncMock(return_value=[ToolResult.fail("boom")])  # type: ignore[method-assign]
    final2, _tools2, msgs2 = await loop._run_agent_loop([{"role": "user", "content": "Read file."}])
    assert final2 == "done2"
    assert any(
        "alternative" in str(m.get("content", "")).lower()
        for m in msgs2
        if m.get("role") == "system"
    )


def test_store_load_rollout_config_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)

    store._rollout_config.apply_overrides(
        {
            "reranker_mode": "enabled",
        }
    )
    assert store.rollout["reranker_mode"] == "enabled"

    store._rollout_config.apply_overrides(
        {
            "rollout_gates": {"min_precision_at_k": 0.6},
            "reranker_alpha": "bad",
            "reranker_mode": "enabled",
        }
    )
    assert store.rollout["reranker_mode"] == "enabled"
    assert store.rollout["rollout_gates"]["min_precision_at_k"] == pytest.approx(0.6)


async def test_loop_run_agent_nudge_and_reaction_and_close_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="t1", name="list_dir", arguments={"path": "."})],
            ),
            LLMResponse(content=""),
            LLMResponse(content="final response"),
        ]
    )
    loop = _make_loop(tmp_path, provider)

    final, _tools, msgs = await loop._run_agent_loop(
        [{"role": "user", "content": "inspect workspace"}],
    )
    assert final == "final response"
    assert any(
        isinstance(m.get("content"), str)
        and "final answer summarizing the tool results" in m["content"]
        for m in msgs
        if m.get("role") == "system"
    )

    # reaction branches: unmapped emoji no-op + mapped emoji executes feedback tool
    await loop.handle_reaction(
        ReactionEvent(channel="cli", sender_id="u", chat_id="c", emoji="zzz")
    )
    await loop.handle_reaction(ReactionEvent(channel="cli", sender_id="u", chat_id="c", emoji="+1"))

    # close_mcp handles RuntimeError from stack cleanup + provider cleanup exception
    class _Stack:
        async def aclose(self):
            raise RuntimeError("cancel scope")

    loop._mcp_stack = _Stack()

    async def _provider_close_fail():
        raise RuntimeError("provider close")

    loop.provider.aclose = _provider_close_fail  # type: ignore[method-assign]
    await loop.close_mcp()
    assert loop._mcp_stack is None


async def test_loop_dispatch_delegation_route_and_exception_paths(tmp_path: Path) -> None:
    from nanobot.agent.delegation import DelegationDispatcher

    loop = object.__new__(AgentLoop)
    loop.role_name = "general"
    loop._coordinator = None
    dispatcher = object.__new__(DelegationDispatcher)
    dispatcher.delegation_count = 0
    dispatcher.routing_trace = []
    dispatcher.coordinator = None
    dispatcher.active_messages = None
    dispatcher.role_name = "general"
    dispatcher.on_progress = None
    dispatcher.record_route_trace = MagicMock()
    loop._dispatcher = dispatcher

    with pytest.raises(Exception, match="."):  # noqa: B017
        await loop._dispatcher.dispatch("", "task", None)

    class _Coord:
        @staticmethod
        def route_direct(_name: str):
            return None

        @staticmethod
        async def route(_task: str):
            return SimpleNamespace(name="code")

    dispatcher.coordinator = _Coord()

    async def _explode(_role, _task, _context):
        raise RuntimeError("delegated fail")

    dispatcher.execute_delegated_agent = _explode  # type: ignore[method-assign]
    token = _delegation_ancestry.set(tuple())
    try:
        with pytest.raises(RuntimeError):
            await loop._dispatcher.dispatch("missing", "find bug", "ctx")
    finally:
        _delegation_ancestry.reset(token)

    assert dispatcher.record_route_trace.call_count >= 2


def test_extractor_entity_and_graph_exception_paths(tmp_path: Path) -> None:
    entities = MemoryExtractor._extract_entities('met "Project Alpha" with Google Chrome in Paris')
    assert entities

    graph = KnowledgeGraph(workspace=tmp_path)

    import asyncio

    async def _run_checks() -> None:
        assert await graph.get_entity("oauth2") is None
        assert await graph.search_entities("oauth2") == []

    asyncio.run(_run_checks())


def test_store_query_hint_status_and_recency_helpers(tmp_path: Path) -> None:
    hints = RetrievalPlanner.query_routing_hints("show pending and completed tasks")
    assert hints["requires_open"] is False
    assert hints["requires_resolved"] is False

    assert (
        RetrievalPlanner.status_matches_query_hint(
            status="closed",
            summary="done",
            requires_open=True,
            requires_resolved=False,
        )
        is False
    )
    assert (
        RetrievalPlanner.status_matches_query_hint(
            status="",
            summary="still in progress",
            requires_open=True,
            requires_resolved=False,
        )
        is True
    )
    assert (
        RetrievalPlanner.status_matches_query_hint(
            status="open",
            summary="todo",
            requires_open=False,
            requires_resolved=True,
        )
        is False
    )

    assert RetrievalPlanner.recency_signal("", half_life_days=10.0) == 0.0
    assert RetrievalPlanner.recency_signal("2026-01-01T00:00:00", half_life_days=0.0) == 0.0
