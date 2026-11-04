import base64
import json
import threading
import zlib

import pytest

from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.history_graph import decode_graph, encode_graph, graph_decoding
from nanobot.session.manager import SessionManager
from nanobot.webui.history import fact_from_record, record_from_fact
from nanobot.webui.transcript import build_webui_thread_response


def graph(count=5):
    return {"nodes": [{"path": f"/{n}.md", "name": f"{n}.md", "tokens": 10, "state": "loaded"} for n in range(count)], "edges": []}


def test_graph_codec_roundtrip_is_self_contained_and_preserves_order():
    original = graph()
    fact = fact_from_record({"event": "model_request", "context_graph": original})
    stored = json.loads(fact.encode())
    assert isinstance(stored["content"]["context_graph"], str)
    restored = record_from_fact(HistoryFact.decode(json.dumps(stored)), "websocket:test")
    assert restored["context_graph"] == original
    # Import/fork re-encoding remains self-contained; no reference table is needed.
    copied = HistoryFact.decode(HistoryFact.decode(fact.encode()).encode())
    assert record_from_fact(copied, "websocket:fork")["context_graph"] == original
    assert fact.content["context_graph"] == original


@pytest.mark.parametrize("value", ["graph-columns-v1:12:12:not-base64", "graph-columns-v1:2:2:" + base64.b64encode(zlib.compress(b"[]" * 1000)).decode(), "zlib-json-v99:anything"])
def test_invalid_graph_does_not_replace_it_with_a_valid_empty_graph(value):
    event = record_from_fact(HistoryFact(HistoryKind.MODEL_REQUEST, {"request_id": "request", "context_graph": value}), "websocket:test")
    assert event["request_id"] == "request"
    assert "context_graph" not in event


def test_byte_limit_still_applies_before_graph_compression(monkeypatch):
    monkeypatch.setattr("nanobot.session.display_history.MAX_HISTORY_FACT_BYTES", 2000)
    with pytest.raises(ValueError, match="8 MiB"):
        HistoryFact(HistoryKind.MODEL_REQUEST, {"context_graph": graph(100)}).encode()


@pytest.mark.parametrize("compressed", [False, True])
def test_each_page_validates_identical_graph_once(monkeypatch, compressed):
    import nanobot.session.history_graph as codec
    value = encode_graph(graph()) if compressed else graph()
    method = "columns" if compressed else "inline"
    original = getattr(codec.GraphDecoder, method)
    calls = 0

    def parse(self, *args):
        nonlocal calls
        calls += 1
        return original(self, *args)

    monkeypatch.setattr(codec.GraphDecoder, method, parse)
    with graph_decoding():
        first = decode_graph(value)
        second = decode_graph(json.loads(json.dumps(value)))
        assert first is second
        assert calls == 1
    first["nodes"].clear()
    with graph_decoding():
        assert len(decode_graph(value)["nodes"]) == 5
        assert calls == 2


async def test_storage_compresses_off_loop_and_replay_retains_each_request(tmp_path, monkeypatch):
    import nanobot.session.history_graph as codec
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = await sessions.state.get("websocket:graph")
    loop_thread = threading.get_ident()
    compress = codec._compress
    calls = []

    def checked(value):
        calls.append(threading.get_ident())
        assert calls[-1] != loop_thread
        return compress(value)

    codec._compress_small.cache_clear()
    monkeypatch.setattr(codec, "_compress", checked)
    for index in range(3):
        await sessions.state.append_history(session.key, [
            fact_from_record({"event": "user", "text": "Question", "turn_id": str(index)}),
            fact_from_record({"event": "model_request", "turn_id": str(index), "request_id": str(index), "run_id": str(index), "sequence": 2, "phase": "completed", "request_usage": {"context_tokens": 10 + index}, "context_graph": graph()}),
            fact_from_record({"event": "turn_end", "turn_id": str(index)}),
        ], expected_generation=session.generation)
    assert len(calls) == 1
    payload = await sessions.state.project_history(session.key, lambda history: build_webui_thread_response(session.key, history=history, include_model_requests=True))
    requests = [event for event in payload["events"] if event["event"] == "model_request"]
    assert [event["request_id"] for event in requests] == ["0", "1", "2"]
    assert [event["request_usage"]["context_tokens"] for event in requests] == [10, 11, 12]
    assert requests[0]["context_graph"] is requests[1]["context_graph"]
    assert requests[0]["context_graph"] == graph()
    await sessions.state.aclose()


def test_oversized_compressible_graph_is_rejected_before_persistence(tmp_path):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    key = "websocket:oversized"
    sessions.get_or_create(key)
    oversized = graph(1)
    oversized["nodes"][0]["name"] = "a" * (8 * 1024 * 1024)
    with pytest.raises(ValueError, match="8 MiB"):
        sessions.append_history(key, [HistoryFact(HistoryKind.MODEL_REQUEST, {"context_graph": oversized})])
    assert sessions.project_history(key, lambda history: list(history.all_facts())) == []


@pytest.mark.parametrize("compressed", [False, True])
def test_growing_snapshots_share_unchanged_entities_but_keep_each_state(compressed):
    initial = graph(2)
    later = graph(3)
    initial["edges"] = [{"source": "/0.md", "target": "/1.md"}]
    later["edges"] = [{"source": "/0.md", "target": "/1.md"}, {"source": "/1.md", "target": "/2.md"}]
    later["nodes"][0]["tokens"] = 20
    with graph_decoding():
        first = decode_graph(encode_graph(initial) if compressed else initial)
        second = decode_graph(encode_graph(later) if compressed else later)
    assert first == initial and second == later
    assert first["nodes"][1] is second["nodes"][1]
    assert first["edges"][0] is second["edges"][0]
    assert first["nodes"][0] is not second["nodes"][0]


@pytest.mark.parametrize("indices", [[0, 99], [True, 0], [0]])
def test_compact_graph_rejects_invalid_edge_indices(indices):
    raw = json.dumps([[["/0.md", "0.md", 10, "loaded"]], indices]).encode()
    encoded = f"graph-columns-v1:1000:{len(raw)}:" + base64.b64encode(zlib.compress(raw)).decode()
    assert decode_graph(encoded) is None


async def test_recorder_batch_encodes_once_off_loop_and_keeps_valid_members(tmp_path, monkeypatch):
    from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
    from nanobot.webui.transcript import WebUITranscriptRecorder

    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = await sessions.state.get("websocket:batch")
    loop_thread = threading.get_ident()
    encode = HistoryFact.encode
    calls = []

    def checked(fact):
        calls.append(fact.kind)
        assert threading.get_ident() != loop_thread
        return encode(fact)

    monkeypatch.setattr(HistoryFact, "encode", checked)
    recorder = WebUITranscriptRecorder(sessions)
    valid = await recorder.append_many("batch", [
        {"event": "user", "text": "question"},
        {"event": "model_request", "request_id": "request", "run_id": "run", "sequence": 1, "phase": "started", "context_graph": graph()},
        {"event": "message", "text": object()},
    ], metadata={HISTORY_GENERATION_METADATA_KEY: session.generation})
    assert valid is False
    assert calls == [HistoryKind.INPUT, HistoryKind.MODEL_REQUEST, HistoryKind.ANSWER]
    records = await sessions.state.project_history(session.key, lambda history: [record_from_fact(fact, session.key) for fact in history.all_facts()])
    assert [record["event"] for record in records] == ["user", "model_request"]
    assert records[1]["context_graph"] == graph()
    await sessions.state.aclose()


def test_storage_limit_includes_compression_size_metadata(monkeypatch):
    fact = HistoryFact(HistoryKind.MODEL_REQUEST, {"context_graph": graph(1), "text": "answer" * 20})
    encoded = fact.encode()
    raw = json.loads(encoded)
    # Small graphs can expand in storage; the final envelope still obeys the cap.
    assert raw["uncompressed_bytes"] < len(encoded.encode("utf-8")) - 1
    monkeypatch.setattr("nanobot.session.display_history.MAX_HISTORY_FACT_BYTES", len(encoded.encode("utf-8")) - 1)
    with pytest.raises(ValueError, match="8 MiB"):
        fact.encode()
