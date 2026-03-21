from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.memory import extractor as extractor_mod
from nanobot.agent.memory.entity_linker import register_alias, resolve_alias
from nanobot.agent.memory.mem0_adapter import _Mem0Adapter
from nanobot.agent.memory.onnx_reranker import OnnxCrossEncoderReranker
from nanobot.agent.memory.retrieval import (
    _bm25_score,
    _build_bm25_index,
    _keyword_score,
    _local_retrieve,
    _topic_fallback_retrieve,
)
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_extractor() -> extractor_mod.MemoryExtractor:
    return extractor_mod.MemoryExtractor(
        to_str_list=lambda x: [str(i) for i in (x or [])],
        coerce_event=lambda item, source_span: (
            {**item, "source_span": source_span} if isinstance(item, dict) else None
        ),
        utc_now_iso=lambda: "2026-03-11T00:00:00+00:00",
    )


def _adapter(tmp_path: Path) -> _Mem0Adapter:
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
    adapter._fallback_candidates = [("huggingface", {"model": "m"}, 384)]
    adapter.last_add_mode = "unknown"
    adapter._infer_true_disabled = False
    adapter._infer_true_disable_reason = ""
    adapter._add_debug = False
    adapter._verify_write = True
    adapter._force_infer_true = False
    return adapter


class _GetAllClient:
    def __init__(self, payload):
        self.payload = payload

    def get_all(self, *args, **kwargs):
        return self.payload


def test_entity_linker_register_and_resolve_unknown() -> None:
    assert resolve_alias("custom entity") == "custom entity"
    register_alias("svc", "service")
    assert resolve_alias(" svc ") == "service"


def test_retrieval_helper_branches() -> None:
    docs, df, avg = _build_bm25_index([])
    assert docs == [] and df == {} and avg == 1.0
    assert _bm25_score([], ["a"], {}, 1, 1.0) == 0.0
    assert _keyword_score(set(), {"summary": "x"}) == 0.0

    events = [
        {"id": "1", "summary": "oauth setup", "entities": ["api"], "timestamp": "bad-ts"},
        {"id": "2", "summary": "oauth setup", "entities": ["api"], "status": "superseded"},
    ]
    out = _local_retrieve(events, "oauth", recency_half_life_days=30.0, include_superseded=True)
    assert out
    only_active = _local_retrieve(events, "oauth", include_superseded=False)
    assert all(str(item.get("id")) != "2" for item in only_active)

    fb = _topic_fallback_retrieve(
        [
            {"id": "a", "metadata": {"topic": "t1", "memory_type": "m1"}},
            {"id": "b", "metadata": {"topic": "t1", "memory_type": "m1"}},
        ],
        target_topics=["t1"],
        target_memory_types=[],
        exclude_ids=set(),
        top_k=1,
    )
    assert len(fb) == 1


def test_onnx_reranker_model_load_failure_and_graceful_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reranker = OnnxCrossEncoderReranker()
    # Force _ensure_model to fail by patching it
    monkeypatch.setattr(reranker, "_ensure_model", lambda: False)

    items = [{"summary": "x", "score": 0.2, "retrieval_reason": "invalid"}]
    ranked = reranker.rerank("q", items)
    # Graceful degradation: items returned unchanged
    assert ranked[0]["score"] == 0.2


async def test_extractor_parse_and_fallback_paths() -> None:
    ext = _make_extractor()
    assert ext.parse_tool_args("not-json") is None
    assert ext.parse_tool_args(["x"]) is None

    provider = SimpleNamespace(chat=None)

    async def _chat(**_kwargs):
        return LLMResponse(content="noop", tool_calls=[])

    provider.chat = _chat
    old_messages = [
        {"role": "assistant", "content": "ignored"},
        {"role": "user", "content": "short"},
        {"role": "user", "content": "I prefer python not javascript"},
    ]
    events, updates = await ext.extract_structured_memory(
        provider,
        "m",
        current_profile={},
        lines=["x"],
        old_messages=old_messages,
        source_start=3,
    )
    assert ext.last_extraction_source == "heuristic"
    assert isinstance(events, list)
    assert "I prefer" in " ".join(updates["preferences"] + updates["stable_facts"])


def test_mem0_row_and_fallback_helpers(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    assert adapter._rows({"data": [{"id": 1}]}) == [{"id": 1}]
    assert adapter._rows({"memories": [{"id": 2}]}) == [{"id": 2}]

    row = adapter._row_to_item(
        {
            "id": "x",
            "memory": "OAuth2 setup",
            "score": "bad",
            "metadata": {
                "memory_type": "weird",
                "stability": "wild",
                "confidence": "nan",
                "entities": ["oauth2"],
            },
        },
        fallback_score=0.3,
    )
    assert row is not None
    assert row["memory_type"] == "episodic"
    assert row["stability"] == "medium"
    assert row["score"] >= 0.3

    assert adapter._looks_blob_like_summary("# Memory\n## context") is True
    assert adapter._looks_blob_like_summary("line1\nline2\nline3\nline4\nline5") is True

    adapter.client = _GetAllClient(
        [
            {"id": "1", "memory": "OAuth2 token refresh", "metadata": {"source": "chat"}},
            {"id": "2", "memory": "OAuth2 token refresh", "metadata": {"source": "chat"}},
            {"id": "3", "memory": "[runtime context] huge blob", "metadata": {"source": "chat"}},
        ]
    )
    rows, rejected = adapter._fallback_search_via_get_all("oauth2", top_k=3)
    assert len(rows) == 1
    assert rejected >= 1

    assert adapter._history_memory_type("yesterday deploy failed") == "episodic"
    assert adapter._history_memory_type("user must use oauth2") == "semantic"


def test_mem0_history_db_fallback(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    history_db = adapter._local_mem0_dir / "history.db"
    conn = sqlite3.connect(history_db)
    conn.execute(
        """
        CREATE TABLE history (
            memory_id TEXT,
            new_memory TEXT,
            created_at TEXT,
            event TEXT,
            is_deleted INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        "INSERT INTO history(memory_id, new_memory, created_at, event, is_deleted) VALUES (?, ?, ?, ?, 0)",
        ("m1", "OAuth2 flow resolved", "2026-01-01T00:00:00+00:00", "add"),
    )
    conn.commit()
    conn.close()

    out, rejected = adapter._fallback_search_via_history_db("oauth2", top_k=2)
    assert rejected == 0
    assert out and out[0]["summary"].lower().startswith("oauth2")


async def test_extractor_llm_tool_call_non_dict_items_and_invalid_source_span() -> None:
    ext = _make_extractor()

    async def _chat(**_kwargs):
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="t1",
                    name="save_events",
                    arguments={
                        "events": ["bad", {"summary": "x", "source_span": "bad"}],
                        "profile_updates": {},
                    },
                )
            ],
        )

    provider = SimpleNamespace(chat=_chat)
    events, _updates = await ext.extract_structured_memory(
        provider,
        "m",
        current_profile={},
        lines=["msg"],
        old_messages=[{"role": "user", "content": "I prefer concise output"}],
        source_start=9,
    )
    assert ext.last_extraction_source == "llm"
    assert events and events[0]["source_span"] == [9, 9]
