"""Tests for CanonicalEventBuilder and project_to_sse()."""

from __future__ import annotations

import json

from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.web.events import project_to_sse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _builder() -> CanonicalEventBuilder:
    return CanonicalEventBuilder(
        run_id="run_abc",
        session_id="sess_xyz",
        turn_id="turn_00001",
        actor_id="main",
    )


def _fresh_state() -> dict:
    return {"text_started": False, "streamed_text": "", "run_end_usage": None, "run_ended": False}


def _sse_types(chunks: list[str]) -> list[str]:
    """Extract the 'type' field from each SSE chunk."""
    types = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[len("data:") :].strip())
                types.append(payload["type"])
    return types


def _sse_payload(chunk: str) -> dict:
    for line in chunk.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    return {}


# ---------------------------------------------------------------------------
# CanonicalEventBuilder — envelope correctness
# ---------------------------------------------------------------------------


class TestCanonicalEventBuilderEnvelope:
    def test_envelope_fields_present(self):
        b = _builder()
        evt = b.run_start()
        assert evt["v"] == 1
        assert evt["event_id"].startswith("evt_")
        assert evt["run_id"] == "run_abc"
        assert evt["session_id"] == "sess_xyz"
        assert evt["turn_id"] == "turn_00001"
        assert evt["actor"] == {"kind": "agent", "id": "main"}
        assert "ts" in evt
        assert "payload" in evt

    def test_seq_increments(self):
        b = _builder()
        e1 = b.run_start()
        e2 = b.text_delta("hello")
        e3 = b.text_delta("world")
        assert e1["seq"] == 1
        assert e2["seq"] == 2
        assert e3["seq"] == 3

    def test_event_ids_unique(self):
        b = _builder()
        ids = {b.run_start()["event_id"] for _ in range(10)}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# CanonicalEventBuilder — event types
# ---------------------------------------------------------------------------


class TestCanonicalEventBuilderTypes:
    def test_run_start(self):
        evt = _builder().run_start()
        assert evt["type"] == "run.start"

    def test_run_end(self):
        evt = _builder().run_end(input_tokens=100, output_tokens=50)
        assert evt["type"] == "run.end"
        assert evt["payload"]["usage"]["input_tokens"] == 100
        assert evt["payload"]["usage"]["output_tokens"] == 50
        assert evt["payload"]["finish_reason"] == "stop"

    def test_text_delta(self):
        evt = _builder().text_delta("Hello")
        assert evt["type"] == "message.part"
        assert evt["payload"]["part_type"] == "text"
        assert evt["payload"]["text"] == "Hello"

    def test_text_flush(self):
        evt = _builder().text_flush("Hello world")
        assert evt["type"] == "message.part"
        assert evt["payload"]["part_type"] == "text_flush"
        assert evt["payload"]["text"] == "Hello world"

    def test_tool_call(self):
        evt = _builder().tool_call("tc_001", "read_file", {"path": "foo.py"})
        assert evt["type"] == "tool.call.start"
        p = evt["payload"]
        assert p["tool_call_id"] == "tc_001"
        assert p["tool_name"] == "read_file"
        assert p["args"] == {"path": "foo.py"}

    def test_tool_result_success(self):
        evt = _builder().tool_result("tc_001", "read_file", "file contents here")
        assert evt["type"] == "tool.result"
        p = evt["payload"]
        assert p["status"] == "success"
        assert p["output"]["text"] == "file contents here"

    def test_tool_result_error(self):
        evt = _builder().tool_result("tc_001", "read_file", "not found", is_error=True)
        assert evt["payload"]["status"] == "error"

    def test_keepalive(self):
        evt = _builder().keepalive()
        assert evt["type"] == "keepalive"
        assert evt["payload"]["scope"] == "transport"

    def test_status(self):
        evt = _builder().status("thinking", label="Planning next step")
        assert evt["type"] == "status"
        assert evt["payload"]["code"] == "thinking"
        assert evt["payload"]["label"] == "Planning next step"

    def test_message_start(self):
        evt = _builder().message_start("msg_001")
        assert evt["type"] == "message.start"
        assert evt["payload"]["message_id"] == "msg_001"
        assert evt["payload"]["role"] == "assistant"

    def test_message_end(self):
        evt = _builder().message_end("msg_001", input_tokens=10, output_tokens=5)
        assert evt["type"] == "message.end"
        p = evt["payload"]
        assert p["message_id"] == "msg_001"
        assert p["finish_reason"] == "stop"
        assert p["usage"]["input_tokens"] == 10
        assert p["usage"]["output_tokens"] == 5


# ---------------------------------------------------------------------------
# project_to_sse — text streaming
# ---------------------------------------------------------------------------


class TestProjectToSseText:
    def test_text_delta_opens_segment_and_emits_delta(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.text_delta("Hello"), text_state=state)
        types = _sse_types(chunks)
        assert types == ["text-start", "text-delta"]
        assert state["text_started"] is True
        assert state["streamed_text"] == "Hello"

    def test_subsequent_deltas_no_extra_text_start(self):
        b = _builder()
        state = _fresh_state()
        project_to_sse(b.text_delta("Hello"), text_state=state)
        chunks2 = project_to_sse(b.text_delta(" world"), text_state=state)
        types2 = _sse_types(chunks2)
        assert "text-start" not in types2
        assert "text-delta" in types2
        assert state["streamed_text"] == "Hello world"

    def test_text_delta_content(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.text_delta("Hi"), text_state=state)
        payload = _sse_payload(chunks[-1])
        assert payload["textDelta"] == "Hi"

    def test_empty_text_delta_emits_nothing(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.text_delta(""), text_state=state)
        assert chunks == []
        assert state["text_started"] is False

    def test_text_flush_deduplicates_already_streamed(self):
        b = _builder()
        state = _fresh_state()
        # Stream "Hello" as delta first
        project_to_sse(b.text_delta("Hello"), text_state=state)
        # Flush with "Hello world" — should only emit " world"
        chunks = project_to_sse(b.text_flush("Hello world"), text_state=state)
        types = _sse_types(chunks)
        assert types == ["text-delta"]
        payload = _sse_payload(chunks[0])
        assert payload["textDelta"] == " world"

    def test_text_flush_skips_subset_of_streamed(self):
        b = _builder()
        state = _fresh_state()
        project_to_sse(b.text_delta("Hello world"), text_state=state)
        # Flush with shorter text — already streamed more, skip
        chunks = project_to_sse(b.text_flush("Hello"), text_state=state)
        assert chunks == []

    def test_text_flush_new_content_when_nothing_streamed(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.text_flush("Fresh text"), text_state=state)
        types = _sse_types(chunks)
        assert "text-start" in types
        assert "text-delta" in types


# ---------------------------------------------------------------------------
# project_to_sse — tool lifecycle
# ---------------------------------------------------------------------------


class TestProjectToSseTool:
    def test_tool_call_emits_triple(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.tool_call("tc1", "exec", {"cmd": "ls"}), text_state=state)
        types = _sse_types(chunks)
        assert types == ["tool-call-start", "tool-call-delta", "tool-call-end"]

    def test_tool_call_closes_open_text_segment(self):
        b = _builder()
        state = _fresh_state()
        project_to_sse(b.text_delta("Thinking"), text_state=state)
        chunks = project_to_sse(b.tool_call("tc1", "exec", {}), text_state=state)
        types = _sse_types(chunks)
        assert types[0] == "text-end"
        assert state["text_started"] is False
        assert state["streamed_text"] == ""

    def test_tool_call_args_serialized_to_json(self):
        b = _builder()
        state = _fresh_state()
        args = {"path": "src/main.py", "lines": [1, 10]}
        chunks = project_to_sse(b.tool_call("tc1", "read_file", args), text_state=state)
        delta_payload = _sse_payload(chunks[1])
        assert delta_payload["type"] == "tool-call-delta"
        parsed_args = json.loads(delta_payload["argsText"])
        assert parsed_args == args

    def test_tool_result_success(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.tool_result("tc1", "exec", "output here"), text_state=state)
        types = _sse_types(chunks)
        assert types == ["tool-result"]
        p = _sse_payload(chunks[0])
        assert p["toolCallId"] == "tc1"
        assert p["result"] == "output here"
        assert p["isError"] is False

    def test_tool_result_error(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(
            b.tool_result("tc1", "exec", "file not found", is_error=True), text_state=state
        )
        p = _sse_payload(chunks[0])
        assert p["isError"] is True


# ---------------------------------------------------------------------------
# project_to_sse — run lifecycle
# ---------------------------------------------------------------------------


class TestProjectToSseRunLifecycle:
    def test_run_start_emits_nothing(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.run_start(), text_state=state)
        assert chunks == []

    def test_run_end_stores_usage_in_state(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.run_end(input_tokens=200, output_tokens=80), text_state=state)
        assert chunks == []
        assert state["run_end_usage"] == {"input_tokens": 200, "output_tokens": 80}
        assert state["run_ended"] is True

    def test_message_start_emits_nothing(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.message_start("msg_001"), text_state=state)
        assert chunks == []

    def test_message_end_stores_usage_same_as_run_end(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(
            b.message_end("msg_001", input_tokens=50, output_tokens=20), text_state=state
        )
        assert chunks == []
        assert state["run_end_usage"] == {"input_tokens": 50, "output_tokens": 20}
        assert state["run_ended"] is True

    def test_keepalive_emits_nothing(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.keepalive(), text_state=state)
        assert chunks == []

    def test_unknown_type_emits_nothing(self):
        state = _fresh_state()
        chunks = project_to_sse({"type": "unknown.event", "payload": {}}, text_state=state)
        assert chunks == []

    def test_message_end_and_run_end_both_set_run_ended(self):
        """Both message.end and run.end set run_ended — first one wins for usage."""
        b = _builder()
        state = _fresh_state()
        project_to_sse(b.message_end("m1", input_tokens=10, output_tokens=5), text_state=state)
        assert state["run_ended"] is True
        assert state["run_end_usage"] == {"input_tokens": 10, "output_tokens": 5}
        # A subsequent run.end should not overwrite (already ended)
        project_to_sse(b.run_end(input_tokens=99, output_tokens=99), text_state=state)
        # run_end_usage overwrites — that's fine, it's a log-level concern not SSE
        assert state["run_ended"] is True


# ---------------------------------------------------------------------------
# project_to_sse — status events
# ---------------------------------------------------------------------------


class TestProjectToSseStatus:
    def test_status_event_emits_sse(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.status("thinking"), text_state=state)
        assert len(chunks) == 1
        p = _sse_payload(chunks[0])
        assert p["type"] == "status"
        assert p["code"] == "thinking"

    def test_status_with_label(self):
        b = _builder()
        state = _fresh_state()
        chunks = project_to_sse(b.status("calling_tool", label="Reading file"), text_state=state)
        p = _sse_payload(chunks[0])
        assert p["label"] == "Reading file"


# ---------------------------------------------------------------------------
# project_to_sse — full turn sequence
# ---------------------------------------------------------------------------


class TestProjectToSseFullTurn:
    def test_text_then_tool_then_text(self):
        """Simulate: stream text → tool call → tool result → more text."""
        b = _builder()
        state = _fresh_state()
        all_types = []

        all_types += _sse_types(project_to_sse(b.text_delta("Let me check"), text_state=state))
        all_types += _sse_types(
            project_to_sse(b.tool_call("tc1", "read_file", {"path": "a.py"}), text_state=state)
        )
        all_types += _sse_types(
            project_to_sse(b.tool_result("tc1", "read_file", "content"), text_state=state)
        )
        all_types += _sse_types(project_to_sse(b.text_delta("Found it."), text_state=state))

        assert all_types == [
            "text-start",
            "text-delta",  # "Let me check"
            "text-end",  # closed by tool call
            "tool-call-start",
            "tool-call-delta",
            "tool-call-end",
            "tool-result",
            "text-start",  # re-opened after tool
            "text-delta",  # "Found it."
        ]
