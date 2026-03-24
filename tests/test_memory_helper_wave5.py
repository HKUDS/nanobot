from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.memory.graph.entity_linker import register_alias, resolve_alias
from nanobot.memory.ranking.onnx_reranker import OnnxCrossEncoderReranker
from nanobot.memory.write import extractor as extractor_mod
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_extractor() -> extractor_mod.MemoryExtractor:
    return extractor_mod.MemoryExtractor(
        to_str_list=lambda x: [str(i) for i in (x or [])],
        coerce_event=lambda item, source_span: (
            {**item, "source_span": source_span} if isinstance(item, dict) else None
        ),
        utc_now_iso=lambda: "2026-03-11T00:00:00+00:00",
    )


def test_entity_linker_register_and_resolve_unknown() -> None:
    assert resolve_alias("custom entity") == "custom entity"
    register_alias("svc", "service")
    assert resolve_alias(" svc ") == "service"


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
