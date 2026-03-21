from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop, _delegation_ancestry
from nanobot.agent.memory import mem0_adapter as mem0_mod
from nanobot.agent.memory.extractor import MemoryExtractor
from nanobot.agent.memory.graph import KnowledgeGraph
from nanobot.agent.memory.mem0_adapter import _Mem0Adapter
from nanobot.agent.memory.persistence import MemoryPersistence
from nanobot.agent.tools.base import ToolResult
from nanobot.bus.events import InboundMessage, ReactionEvent
from nanobot.providers.base import LLMResponse, ToolCallRequest
from tests.test_agent_loop import ScriptedProvider, _make_loop
from tests.test_store_helpers import _store


class _FallbackClient:
    @staticmethod
    def from_config(_payload):
        return SimpleNamespace()


def _make_adapter(tmp_path: Path) -> _Mem0Adapter:
    adapter = object.__new__(_Mem0Adapter)
    adapter.workspace = tmp_path
    adapter.user_id = "nanobot"
    adapter.enabled = True
    adapter.client = None
    adapter.mode = "oss"
    adapter.error = None
    adapter._local_fallback_attempted = False
    adapter._local_mem0_dir = tmp_path / "memory" / "mem0"
    adapter._local_mem0_dir.mkdir(parents=True, exist_ok=True)
    adapter._fallback_enabled = True
    adapter._fallback_candidates = [("huggingface", {"model": "x"}, 128)]
    adapter.last_add_mode = "unknown"
    adapter._infer_true_disabled = False
    adapter._infer_true_disable_reason = ""
    adapter._add_debug = False
    adapter._verify_write = True
    adapter._force_infer_true = False
    return adapter


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
    loop.context.memory.ask_user_for_conflict = MagicMock(return_value="Please resolve conflict")
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

    monkeypatch.setattr(loop, "_consolidate_memory", _no_archive)
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

    monkeypatch.setattr(loop, "_consolidate_memory", _boom)

    out = await loop._process_message(
        InboundMessage(channel="cli", chat_id="room2", sender_id="u", content="/new")
    )
    assert out is not None
    assert "failed" in out.content.lower()


def test_store_retrieve_core_router_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(
        tmp_path,
        memory_router_enabled=True,
        memory_reflection_enabled=True,
        memory_type_separation_enabled=True,
        memory_history_fallback_enabled=True,
        reranker_mode="shadow",
    )

    # Use synthetic retrieval payload to cover intent filters and adjustment logic.
    rows = [
        {
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "type": "fact",
            "summary": "rollout reflection shadow mode status",
            "topic": "rollout",
            "score": 0.8,
            "memory_type": "semantic",
            "stability": "high",
            "retrieval_reason": {"provider": "mem0"},
            "evidence_refs": [],
        },
        {
            "id": "e2",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "type": "fact",
            "summary": "postmortem reflection output",
            "topic": "incident",
            "score": 0.6,
            "memory_type": "reflection",
            "stability": "low",
            "retrieval_reason": {"provider": "mem0"},
            "evidence_refs": ["ev1"],
        },
        {
            "id": "e3",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "type": "task",
            "summary": "open task plan next step milestone",
            "topic": "planning",
            "score": 0.7,
            "memory_type": "episodic",
            "status": "open",
            "retrieval_reason": {"provider": "mem0"},
            "evidence_refs": [],
        },
    ]

    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=(
            rows,
            {"source_vector": 2, "source_get_all": 1, "source_history": 1, "rejected_blob_like": 0},
        )
    )
    store.graph.enabled = True
    store.graph.get_related_entity_names_sync = MagicMock(return_value={"oauth2"})
    store.read_events = MagicMock(
        return_value=[{"id": "extra", "summary": "oauth2 rollout", "entities": []}]
    )
    monkeypatch.setattr("nanobot.agent.memory.store._local_retrieve", lambda *args, **kwargs: [])

    class _Reranker:
        available = True

        @staticmethod
        def rerank(_query, items):
            return list(reversed(items))

        @staticmethod
        def compute_rank_delta(_a, _b):
            return 0.4

    store._reranker = _Reranker()

    final, meta = store._retrieve_core(
        query="what is rollout status",
        top_k=2,
        router_enabled=True,
        type_separation_enabled=True,
        reflection_enabled=True,
    )
    assert final
    assert meta["counts"]["retrieval_returned"] >= 1

    # Reflection intent includes reflection rows.
    final_reflect, _meta_reflect = store._retrieve_core(
        query="reflect on failures",
        top_k=3,
        router_enabled=True,
        type_separation_enabled=True,
        reflection_enabled=True,
    )
    assert any(str(it.get("memory_type")) == "reflection" for it in final_reflect)


def test_mem0_activate_local_fallback_and_search_fallback_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _make_adapter(tmp_path)

    # Guard branches.
    monkeypatch.setattr("nanobot.agent.memory.mem0_adapter.Mem0Memory", None)
    assert adapter._activate_local_fallback(reason="no mem0") is False

    monkeypatch.setattr("nanobot.agent.memory.mem0_adapter.Mem0Memory", _FallbackClient)
    adapter._fallback_enabled = False
    assert adapter._activate_local_fallback(reason="disabled") is False

    adapter._fallback_enabled = True
    adapter.mode = "hosted"
    assert adapter._activate_local_fallback(reason="hosted") is False

    adapter.mode = "oss"
    adapter._local_fallback_attempted = False
    assert adapter._activate_local_fallback(reason="retry") is True
    assert adapter.enabled is True
    assert "oss-local-fallback" in adapter.mode

    class _SearchTypeErrThenErr:
        def __init__(self):
            self.calls = 0

        def search(self, *args, **kwargs):
            self.calls += 1
            if "query" in kwargs:
                raise TypeError("kw")
            raise RuntimeError("fail")

    adapter.enabled = True
    adapter.client = _SearchTypeErrThenErr()
    adapter._activate_local_fallback = MagicMock(return_value=False)
    out = adapter.search("abc", return_stats=True)
    assert out[0] == []


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

    graph = KnowledgeGraph.__new__(KnowledgeGraph)
    graph.enabled = False
    graph._driver = None
    graph._sync_driver = None
    graph._database = "neo4j"

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


def test_persistence_invalid_json_and_jsonl_skip(tmp_path: Path) -> None:
    p = MemoryPersistence(tmp_path)

    # read_json -> invalid payload type and parse error branches
    bad_type = tmp_path / "bad_type.json"
    bad_type.write_text('"just a string"', encoding="utf-8")
    assert p.read_json(bad_type) is None

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    assert p.read_json(bad_json) is None

    # read_jsonl -> invalid line branch
    lines = tmp_path / "events.jsonl"
    lines.write_text('{"ok":1}\nnot-json\n{"k":2}\n', encoding="utf-8")
    rows = p.read_jsonl(lines)
    assert len(rows) == 2


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

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _failing_connect)
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


def test_store_retrieve_core_router_off_and_rollout_status(tmp_path: Path) -> None:
    store = _store(tmp_path, memory_router_enabled=False, memory_reflection_enabled=False)
    store.mem0.enabled = True
    store.mem0.search = MagicMock(return_value=[])
    store.graph.enabled = False

    rows, meta = store._retrieve_core(
        query="what is rollout status",
        top_k=1,
        router_enabled=False,
        type_separation_enabled=False,
        reflection_enabled=False,
    )
    assert rows == []
    assert meta["counts"]["retrieval_returned"] == 0

    # Router-enabled rollout path creates a synthetic item.
    store.mem0.search = MagicMock(
        return_value=(
            [],
            {"source_vector": 0, "source_get_all": 0, "source_history": 0, "rejected_blob_like": 0},
        )
    )
    rows2, meta2 = store._retrieve_core(
        query="rollout status",
        top_k=1,
        router_enabled=True,
        type_separation_enabled=True,
        reflection_enabled=True,
    )
    assert rows2
    assert meta2["intent"] == "rollout_status"


async def test_graph_query_subgraph_dedupe_and_get_entity_none() -> None:
    g = KnowledgeGraph.__new__(KnowledgeGraph)
    g.enabled = True
    g._database = "neo4j"
    g._driver = object()
    g._sync_driver = None

    async def _neighbors(name: str, depth: int = 1):
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

    class _NoRecordResult:
        async def single(self):
            return None

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def run(self, *_args, **_kwargs):
            return _NoRecordResult()

    class _Drv:
        def session(self, database: str = "neo4j"):
            return _Sess()

    g2 = KnowledgeGraph.__new__(KnowledgeGraph)
    g2.enabled = True
    g2._database = "neo4j"
    g2._driver = _Drv()
    g2._sync_driver = None
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

    loop._call_llm = AsyncMock(side_effect=responses)  # type: ignore[method-assign]
    loop.tools.execute_batch = AsyncMock(return_value=[ToolResult.ok("ok")])  # type: ignore[method-assign]

    final, _tools, messages = await loop._run_agent_loop(
        [{"role": "user", "content": "Please do this task."}]
    )
    assert final == "final answer"
    assert any(m.get("role") == "tool" for m in messages)


async def test_loop_run_agent_loop_delegation_and_failure_reflection_paths(tmp_path: Path) -> None:
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

    loop._call_llm = AsyncMock(side_effect=responses)  # type: ignore[method-assign]
    loop.tools.execute_batch = _exec  # type: ignore[method-assign]
    final, _tools, msgs = await loop._run_agent_loop([{"role": "user", "content": "Do A then B."}])
    assert final == "done"
    assert any(
        "Delegation budget exhausted" in str(m.get("content", ""))
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
    loop._call_llm = AsyncMock(side_effect=responses2)  # type: ignore[method-assign]
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
    """Verify rollout overrides flow through _apply_rollout_overrides correctly.

    Legacy NANOBOT_* env vars no longer read directly by _load_rollout_config;
    config flows through schema → pydantic-settings → rollout_overrides dict.
    """
    store = _store(tmp_path)

    # Simulate what AgentLoop passes via rollout_overrides
    store._apply_rollout_overrides(
        {
            "memory_rollout_mode": "shadow",
            "memory_fallback_allowed_sources": ["events", "profile"],
            "reranker_mode": "enabled",
        }
    )
    assert store.rollout["memory_rollout_mode"] == "shadow"
    assert store.rollout["memory_fallback_allowed_sources"] == ["events", "profile"]
    assert store.rollout["reranker_mode"] == "enabled"

    store._apply_rollout_overrides(
        {
            "memory_shadow_sample_rate": "bad",
            "memory_fallback_max_summary_chars": "bad",
            "rollout_gates": {"min_recall_at_k": "bad", "min_precision_at_k": 0.6},
            "reranker_alpha": "bad",
            "reranker_mode": "enabled",
        }
    )
    assert store.rollout["reranker_mode"] == "enabled"
    assert store.rollout["rollout_gates"]["min_precision_at_k"] == pytest.approx(0.6)


def test_store_retrieve_core_reranker_enabled_and_type_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, reranker_mode="enabled", memory_reflection_enabled=True)
    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=(
            [
                {
                    "id": "a1",
                    "summary": "semantic line",
                    "type": "fact",
                    "memory_type": "semantic",
                    "stability": "high",
                    "score": 0.5,
                    "retrieval_reason": {},
                },
                {
                    "id": "a2",
                    "summary": "episodic line",
                    "type": "task",
                    "memory_type": "episodic",
                    "stability": "low",
                    "status": "open",
                    "score": 0.4,
                    "retrieval_reason": {},
                },
                {
                    "id": "a3",
                    "summary": "reflection line",
                    "type": "fact",
                    "memory_type": "reflection",
                    "evidence_refs": ["e1"],
                    "score": 0.3,
                    "retrieval_reason": {},
                },
            ],
            {"source_vector": 3, "source_get_all": 0, "source_history": 0, "rejected_blob_like": 0},
        )
    )
    store.graph.enabled = True
    store.graph.get_related_entity_names_sync = MagicMock(return_value={"oauth2"})
    store.read_events = MagicMock(
        return_value=[{"id": "z1", "summary": "oauth2 semantic", "entities": []}]
    )
    monkeypatch.setattr(
        "nanobot.agent.memory.store._local_retrieve",
        lambda *_args, **_kwargs: [
            {"id": "graph-new", "summary": "g", "retrieval_reason": "bad", "score": 0.9}
        ],
    )

    class _EnabledReranker:
        available = True

        @staticmethod
        def rerank(_query, items):
            return list(reversed(items))

    store._reranker = _EnabledReranker()

    final, meta = store._retrieve_core(
        query="open tasks and reflection",
        top_k=4,
        router_enabled=True,
        type_separation_enabled=True,
        reflection_enabled=True,
    )
    assert final
    assert meta["counts"]["retrieval_returned"] >= 1


def test_mem0_load_env_and_api_key_guard_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _make_adapter(tmp_path)

    # _load_fallback_config guard paths
    assert adapter._load_fallback_config(None) == {}
    assert adapter._load_fallback_config({"fallback": "x"}) == {}

    # _load_api_keys_from_config missing/invalid/providers-not-dict paths
    home = tmp_path / "home"
    cfg_dir = home / ".nanobot"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    assert adapter._load_api_keys_from_config() is None
    bad = cfg_dir / "config.json"
    bad.write_text("{", encoding="utf-8")
    assert adapter._load_api_keys_from_config() is None
    bad.write_text(json.dumps({"providers": []}), encoding="utf-8")
    assert adapter._load_api_keys_from_config() is None

    # _load_env_candidates fallback resolve path + read error path
    class _BadFile:
        def expanduser(self):
            return self

        def resolve(self):
            raise OSError("r")

        def exists(self):
            return True

        def is_file(self):
            return True

        def read_text(self, encoding: str = "utf-8"):
            raise OSError("read")

    class _Workspace:
        def __truediv__(self, _x: str):
            return _BadFile()

    adapter.workspace = _Workspace()  # type: ignore[assignment]
    adapter._load_env_candidates()


def test_mem0_add_text_and_history_fallback_rejections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _make_adapter(tmp_path)
    adapter.enabled = True

    class _AddFailClient:
        def add(self, *_args, **_kwargs):
            raise RuntimeError("invalid api key")

    adapter.client = _AddFailClient()
    adapter._add_debug = True
    adapter._verify_write = True
    adapter.get_all_count = MagicMock(side_effect=[1, 1, 1, 1, 1])  # type: ignore[method-assign]
    adapter._activate_local_fallback = MagicMock(return_value=False)
    assert adapter.add_text("hello") is False

    # history fallback branch: reject long and blob-like and duplicate keys
    history_db = adapter._local_mem0_dir / "history.db"
    import sqlite3

    conn = sqlite3.connect(history_db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS history(memory_id TEXT,new_memory TEXT,created_at TEXT,event TEXT,is_deleted INTEGER DEFAULT 0)"
    )
    conn.execute(
        "INSERT INTO history(memory_id,new_memory,created_at,event,is_deleted) VALUES(?,?,?,?,0)",
        ("m1", "[runtime context] very large", "2026-01-01T00:00:00+00:00", "add"),
    )
    conn.execute(
        "INSERT INTO history(memory_id,new_memory,created_at,event,is_deleted) VALUES(?,?,?,?,0)",
        ("m2", "oauth2 token refresh", "2026-01-01T00:00:00+00:00", "add"),
    )
    conn.execute(
        "INSERT INTO history(memory_id,new_memory,created_at,event,is_deleted) VALUES(?,?,?,?,0)",
        ("m3", "oauth2 token refresh", "2026-01-02T00:00:00+00:00", "add"),
    )
    conn.commit()
    conn.close()

    rows, rejected = adapter._fallback_search_via_history_db("oauth2", top_k=5)
    assert len(rows) == 1
    assert rejected >= 1


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
    # Create a minimal dispatcher so that property proxies work
    dispatcher = object.__new__(DelegationDispatcher)
    dispatcher.delegation_count = 0
    dispatcher.routing_trace = []
    dispatcher.coordinator = None
    dispatcher.active_messages = None
    dispatcher.role_name = "general"
    dispatcher.on_progress = None
    dispatcher.record_route_trace = MagicMock()
    loop._dispatcher = dispatcher

    with pytest.raises(Exception, match="."):  # noqa: B017 — any exception signals correct guard
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


def test_store_retrieve_core_profile_adjustment_paths(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        memory_router_enabled=True,
        memory_reflection_enabled=True,
        memory_type_separation_enabled=True,
    )

    rows = [
        {
            "id": "s1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "type": "fact",
            "summary": "oauth2 token refresh failed old value",
            "topic": "constraint",
            "score": 0.6,
            "memory_type": "semantic",
            "status": "superseded",
            "superseded_by_event_id": "s2",
            "retrieval_reason": {},
            "evidence_refs": ["ev"],
        },
        {
            "id": "s2",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "type": "fact",
            "summary": "oauth2 token refresh new value",
            "topic": "constraint",
            "score": 0.7,
            "memory_type": "semantic",
            "retrieval_reason": {},
            "evidence_refs": ["ev2"],
        },
    ]
    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=(
            rows,
            {
                "source_vector": 2,
                "source_get_all": 0,
                "source_history": 0,
                "rejected_blob_like": 0,
            },
        )
    )
    store.read_events = MagicMock(return_value=[])
    store.graph.enabled = False

    profile = {
        "conflicts": [
            "bad-row",
            {
                "status": "resolved",
                "resolution": "keep_new",
                "field": "stable_facts",
                "old": "old value",
                "new": "new value",
            },
        ],
        "meta": {
            "stable_facts": {
                store._norm_text("new value"): {
                    "status": store.PROFILE_STATUS_STALE,
                    "pinned": False,
                }
            }
        },
    }
    store.read_profile = MagicMock(return_value=profile)

    final, _meta = store._retrieve_core(
        query="find constraints",
        top_k=2,
        router_enabled=True,
        type_separation_enabled=True,
        reflection_enabled=True,
    )
    assert final
    assert any("profile_adjustment" in it.get("retrieval_reason", {}) for it in final)


def test_mem0_search_update_delete_and_init_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _make_adapter(tmp_path)

    # _load_fallback_config: non-dict provider item + invalid dims coercion
    fallback = {
        "fallback": {
            "enabled": True,
            "providers": [
                "bad",
                {"provider": "hf", "config": {}, "embedding_model_dims": "bad"},
            ],
        }
    }
    adapter._load_fallback_config(fallback)
    assert adapter._fallback_candidates[0][2] == 384

    class _SearchClient:
        def __init__(self):
            self.calls = 0

        def search(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("primary fail")
            raise TypeError("signature")

        def update(self, *_args, **_kwargs):
            raise TypeError("legacy")

        def delete(self, *_args, **_kwargs):
            raise RuntimeError("delete fail")

    adapter.client = _SearchClient()

    # fallback search TypeError->Exception branch
    adapter._activate_local_fallback = MagicMock(return_value=True)
    result, stats = adapter.search("oauth2", top_k=2, return_stats=True)
    assert result == []
    assert stats["source_vector"] == 0

    # update/delete fallback branches
    assert adapter.update("m1", "text") is False
    assert adapter.delete("m1") is False

    # _init_client hosted path with org/project kwargs
    captured: dict[str, str] = {}

    class _HostedClient:
        def __init__(self, **kwargs):
            captured.update({k: str(v) for k, v in kwargs.items()})

    monkeypatch.setattr(mem0_mod, "Mem0MemoryClient", _HostedClient)
    monkeypatch.setattr(mem0_mod, "Mem0Memory", None)
    monkeypatch.setenv("MEM0_API_KEY", "k")
    monkeypatch.setenv("MEM0_ORG_ID", "org")
    monkeypatch.setenv("MEM0_PROJECT_ID", "proj")
    hosted = _Mem0Adapter(workspace=tmp_path)
    assert hosted.mode in {"hosted", "disabled", "oss"}
    if captured:
        assert captured.get("org_id") == "org"
        assert captured.get("project_id") == "proj"


def test_mem0_additional_branch_clusters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(tmp_path)

    # delete_all_user_memories branches
    adapter.enabled = False
    assert adapter.delete_all_user_memories()[1] == "mem0_disabled"
    adapter.enabled = True

    class _DeleteAllTypeErr:
        def delete_all(self, *_args, **_kwargs):
            raise TypeError("x")

    adapter.client = _DeleteAllTypeErr()
    ok, reason, _count = adapter.delete_all_user_memories()
    assert ok is False
    assert reason.startswith("delete_all_failed:")

    class _DeleteAllErr:
        def delete_all(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    adapter.client = _DeleteAllErr()
    ok2, reason2, _count2 = adapter.delete_all_user_memories()
    assert ok2 is False
    assert reason2.startswith("delete_all_failed:")

    # lexical + row normalization edge paths
    assert adapter._lexical_score("", "x") == 0.0
    assert adapter._lexical_score("alpha", "beta") == 0.0
    assert adapter._row_to_item({"summary": ""}) is None
    item = adapter._row_to_item(
        {"summary": "kept", "metadata": {"confidence": "bad"}},
        fallback_score=0.3,
    )
    assert item is not None
    assert item["confidence"] == 0.7
    assert item["score"] >= 0.3
    assert adapter._looks_blob_like_summary("") is True

    # get_all fallback branches + normalization skip path
    class _GetAllTypeErr:
        def get_all(self, *_args, **_kwargs):
            raise TypeError("sig")

    adapter.client = _GetAllTypeErr()
    assert adapter._fallback_search_via_get_all("q", top_k=2) == ([], 0)

    class _GetAllErr:
        def get_all(self, *_args, **_kwargs):
            raise RuntimeError("x")

    adapter.client = _GetAllErr()
    assert adapter._fallback_search_via_get_all("q", top_k=2) == ([], 0)

    class _GetAllRows:
        @staticmethod
        def get_all(*_args, **_kwargs):
            return [
                {"summary": ""},
                {"summary": "x" * 999},
                {"summary": "[runtime context] blob"},
                {"summary": "other words"},
                {"summary": "oauth2 token", "metadata": {"source": "chat"}},
            ]

    adapter.client = _GetAllRows()
    adapter._row_to_item = MagicMock(return_value=None)  # type: ignore[method-assign]
    rows, rejected = adapter._fallback_search_via_get_all(
        "oauth2",
        top_k=2,
        allowed_sources=None,
    )
    assert rows == []
    assert rejected >= 1

    # history-db guard paths
    adapter._local_mem0_dir = None
    assert adapter._fallback_search_via_history_db("q", top_k=1) == ([], 0)
    adapter._local_mem0_dir = tmp_path / "missing_mem0"
    adapter._local_mem0_dir.mkdir(parents=True, exist_ok=True)
    assert adapter._fallback_search_via_history_db("q", top_k=1) == ([], 0)

    # add_text local fallback forced infer_true branch cluster
    class _AddClient:
        def add(self, *_args, **kwargs):
            if kwargs.get("infer") is True:
                raise RuntimeError("invalid api key")
            raise RuntimeError("fail")

    adapter.client = _AddClient()
    adapter.enabled = True
    adapter.mode = "oss"
    adapter.get_all_count = MagicMock(return_value=0)  # type: ignore[method-assign]
    adapter._activate_local_fallback = MagicMock(return_value=True)
    adapter._force_infer_true = True
    assert adapter.add_text("hello") is False


def test_store_routing_hint_and_reflection_filters(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        memory_router_enabled=True,
        memory_reflection_enabled=True,
        memory_type_separation_enabled=True,
    )
    rows = [
        {
            "id": "r1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "type": "fact",
            "summary": "plain fact",
            "topic": "general",
            "score": 0.5,
            "memory_type": "reflection",
            "evidence_refs": [],
            "retrieval_reason": {},
        }
    ]
    store.mem0.enabled = True
    store.mem0.search = MagicMock(
        return_value=(
            rows,
            {"source_vector": 1, "source_get_all": 0, "source_history": 0, "rejected_blob_like": 0},
        )
    )
    store.read_events = MagicMock(return_value=[])
    store.read_profile = MagicMock(return_value={"conflicts": [], "meta": {}})
    store._query_routing_hints = MagicMock(
        return_value={
            "focus_task_decision": False,
            "focus_planning": True,
            "focus_architecture": True,
            "requires_open": False,
            "requires_resolved": False,
        }
    )
    store._status_matches_query_hint = MagicMock(return_value=True)
    out, _meta = store._retrieve_core(
        query="planning architecture",
        top_k=2,
        router_enabled=True,
        type_separation_enabled=True,
        reflection_enabled=True,
    )
    assert out == []


def test_extractor_entity_and_graph_exception_paths(tmp_path: Path) -> None:
    entities = MemoryExtractor._extract_entities('met "Project Alpha" with Google Chrome in Paris')
    assert entities

    graph = object.__new__(KnowledgeGraph)
    graph.enabled = True
    graph._database = None

    class _Driver:
        def session(self, **_kwargs):
            class _SessionCtx:
                async def __aenter__(self):
                    raise RuntimeError("neo4j down")

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return _SessionCtx()

    graph._driver = _Driver()

    async def _run_checks():
        assert await graph.get_entity("oauth2") is None
        assert await graph.search_entities("oauth2") == []

    import asyncio

    asyncio.run(_run_checks())


def test_store_query_hint_status_and_recency_helpers(tmp_path: Path) -> None:
    store = _store(tmp_path)

    hints = store._query_routing_hints("show pending and completed tasks")
    assert hints["requires_open"] is False
    assert hints["requires_resolved"] is False

    assert (
        store._status_matches_query_hint(
            status="closed",
            summary="done",
            requires_open=True,
            requires_resolved=False,
        )
        is False
    )
    assert (
        store._status_matches_query_hint(
            status="",
            summary="still in progress",
            requires_open=True,
            requires_resolved=False,
        )
        is True
    )
    assert (
        store._status_matches_query_hint(
            status="open",
            summary="todo",
            requires_open=False,
            requires_resolved=True,
        )
        is False
    )

    assert store._recency_signal("", half_life_days=10.0) == 0.0
    assert store._recency_signal("2026-01-01T00:00:00", half_life_days=0.0) == 0.0


def test_mem0_remaining_helper_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter(tmp_path)

    adapter.client = None
    assert adapter._fallback_search_via_get_all("q", top_k=1) == ([], 0)

    class _RaiseSearch:
        @staticmethod
        def search(*_args, **_kwargs):
            raise RuntimeError("boom")

    adapter.client = _RaiseSearch()
    adapter._activate_local_fallback = MagicMock(return_value=False)
    rows, stats = adapter.search("q", top_k=1, return_stats=True)
    assert rows == []
    assert stats["source_get_all"] == 0

    adapter._local_mem0_dir = tmp_path / "mem0_exc"
    adapter._local_mem0_dir.mkdir(parents=True, exist_ok=True)
    (adapter._local_mem0_dir / "history.db").write_text("x", encoding="utf-8")
    import sqlite3

    monkeypatch.setattr(
        sqlite3, "connect", lambda *_a, **_k: (_ for _ in ()).throw(sqlite3.OperationalError("db"))
    )
    assert adapter._fallback_search_via_history_db("q", top_k=1) == ([], 0)
