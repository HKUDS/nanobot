"""Anthropic replay across an in-turn checkpoint and a session reopen (#6786)."""

import json
from unittest.mock import AsyncMock

import anthropic
import httpx

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.base import GenerationSettings
from nanobot.session.manager import SessionManager
from nanobot.session.summary import is_summary_checkpoint

_MODEL = "claude-sonnet-5-5"
_SUMMARY = "The user asked for the contents of the note."


def _stream_reply(blocks, stop_reason, input_tokens):
    events = [{"type": "message_start", "message": {
        "type": "message", "id": "msg_1", "role": "assistant", "model": _MODEL, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": input_tokens, "output_tokens": 0},
    }}]
    for index, block in enumerate(blocks):
        events.extend([
            {"type": "content_block_start", "index": index, "content_block": block},
            {"type": "content_block_stop", "index": index},
        ])
    events.extend([
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 8}},
        {"type": "message_stop"},
    ])
    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content="".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ))


async def test_anthropic_replay_after_in_turn_compaction_and_reopen(tmp_path, monkeypatch):
    requests = []

    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            return _stream_reply([
                {"type": "thinking", "thinking": "Find the note.", "signature": "index-signature"},
                {"type": "tool_use", "id": "toolu_index", "name": "read_file", "input": {"path": "index.txt"}},
            ], "tool_use", 100)
        if len(requests) == 2:
            # Report enough usage to trigger the real governor on the next tool continuation.
            return _stream_reply([
                {"type": "thinking", "thinking": "Read the note.", "signature": "note-signature"},
                {"type": "tool_use", "id": "toolu_read", "name": "read_file", "input": {"path": "note.txt"}},
            ], "tool_use", 199_000)
        return _stream_reply([{"type": "text", "text": "Noted."}], "end_turn", 100)

    client = anthropic.AsyncAnthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: client(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)), **kwargs,
    ))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "index.txt").write_text("note.txt", encoding="utf-8")
    (workspace / "note.txt").write_text("orchard inventory", encoding="utf-8")
    summarize = AsyncMock(return_value=_SUMMARY)
    for prompt in ("Read note.txt", "Continue the inventory"):
        provider = AnthropicProvider(
            api_key="test", default_model=_MODEL, extra_headers={"Anthropic-Beta": "other-beta"},
        )
        provider.generation = GenerationSettings(reasoning_effort="medium")
        sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
        loop = AgentLoop(
            bus=MessageBus(), provider=provider, workspace=workspace, session_manager=sessions,
            context_window_tokens=200_000, restrict_to_workspace=True,
        )
        monkeypatch.setattr(loop.consolidator, "summarize_transcript", summarize)
        try:
            if requests:
                reopened = sessions.get_existing("cli:direct")
                assert reopened is not None
                assert is_summary_checkpoint(reopened.messages[reopened.last_archived])
                assert reopened.metadata["_last_summary"]["text"] == _SUMMARY
                assert any(
                    b["signature"] == "note-signature"
                    for msg in reopened.get_history() for b in msg.get("thinking_blocks", [])
                )
            result = await loop.process_direct(prompt)
            assert result is not None and result.content == "Noted."
        finally:
            await loop.aclose()

    summarize.assert_awaited_once()
    original, uncompacted, compacted, resumed = requests
    assert json.loads(original.content)["model"] == _MODEL
    assert "Read note.txt" in json.dumps(json.loads(original.content)["messages"])
    assert "Continue the inventory" in json.dumps(json.loads(resumed.content)["messages"])

    def blocks_in(body):
        return [block for msg in body["messages"] if isinstance(msg["content"], list) for block in msg["content"]]

    unchanged = blocks_in(json.loads(uncompacted.content))
    assert [b["signature"] for b in unchanged if b["type"] == "thinking"] == ["index-signature"]
    assert any(b["type"] == "tool_use" and b["id"] == "toolu_index" for b in unchanged)
    assert any(b["type"] == "tool_result" and b["tool_use_id"] == "toolu_index" for b in unchanged)

    assert uncompacted.headers["anthropic-beta"] == "other-beta"
    for request in (compacted, resumed):
        body = json.loads(request.content)
        assert _SUMMARY in json.dumps(body["system"])
        assert "Read note.txt" not in json.dumps(body["messages"])
        blocks = blocks_in(body)
        assert any(b["type"] == "tool_use" and b["id"] == "toolu_read" for b in blocks)
        assert any(b["type"] == "tool_result" and b["tool_use_id"] == "toolu_read"
                   and "orchard inventory" in b["content"] for b in blocks)
        assert [b["signature"] for b in blocks if b["type"] == "thinking"] == ["note-signature"]
        assert body["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
        assert request.headers["anthropic-beta"].split(",") == ["other-beta", "thinking-binding-controls-2026-08-01"]
