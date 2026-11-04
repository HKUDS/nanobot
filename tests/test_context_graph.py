import json
from pathlib import Path

from nanobot.context_graph import graph_from_messages, source_metadata, source_receipt


def test_markdown_discovers_only_real_local_links_without_reading_targets(tmp_path: Path):
    content = """[Guide](references/guide.md#setup)
[Other][ref]

[ref]: other.md

[Site](https://example.com)
[Anchor](#heading)
`[code](not-a-link.md)`
```
[example](also-not-a-link.md)
```
"""
    source = source_receipt(tmp_path / "SKILL.md", content)
    assert source["links"] == [str(tmp_path / "references" / "guide.md"), str(tmp_path / "other.md")]
    graph = graph_from_messages([{"content": content, "_meta": source_metadata(content, [source])}])
    assert [node["state"] for node in graph["nodes"]] == ["loaded", "discovered", "discovered"]


def test_compacted_or_removed_content_no_longer_counts_as_loaded(tmp_path: Path):
    content = "[Child](child.md)"
    metadata = source_metadata(content, [source_receipt(tmp_path / "parent.md", content)])
    assert graph_from_messages([{"content": "Summary of earlier work", "_meta": metadata}]) == {"nodes": [], "edges": []}
    assert graph_from_messages([]) == {"nodes": [], "edges": []}


def test_retained_partial_reads_accumulate_without_loading_entire_file(tmp_path: Path):
    path = tmp_path / "large.md"
    messages = []
    for content in ["First fragment", "Second fragment"]:
        receipt = source_receipt(path, content)
        messages.append({"content": content, "_meta": source_metadata(content, [receipt])})
    graph = graph_from_messages(messages)
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["tokens"] == sum(source_receipt(path, text)["tokens"] for text in ["First fragment", "Second fragment"])
    assert graph_from_messages(messages[1:])["nodes"][0]["tokens"] < graph["nodes"][0]["tokens"]


def test_system_sources_track_actual_injection_and_skill_metadata(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder

    (tmp_path / "SOUL.md").write_text("Be precise", encoding="utf-8")
    skill = tmp_path / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example\n---\n[Reference](ref.md)", encoding="utf-8")
    graph = graph_from_messages(ContextBuilder(tmp_path).build_messages([], "Hello"))
    by_path = {node["path"]: node for node in graph["nodes"]}
    assert by_path[str(tmp_path / "SOUL.md")]["state"] == "loaded"
    assert by_path[str(skill / "SKILL.md")]["state"] == "discovered"
    assert str(skill / "ref.md") not in by_path


def test_file_provenance_survives_saved_turn_and_replay(tmp_path: Path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.session.manager import Session

    content = "[Reference](reference.md)"
    message = {"role": "tool", "tool_call_id": "read-1", "content": content,
               "_meta": source_metadata(content, [source_receipt(tmp_path / "guide.md", content)])}
    session = Session(key="test:context-graph")
    loop = object.__new__(AgentLoop)
    loop._save_turn(session, [
        {"role": "user", "content": "Read the guide"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "read-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
        ]}, message,
    ], skip=0)
    restored = Session(key=session.key, messages=json.loads(json.dumps(session.messages)))
    assert graph_from_messages(restored.get_history()) == graph_from_messages([message])
    restored.commit_summary_checkpoint("Guide reviewed")
    assert graph_from_messages(restored.get_history()) == {"nodes": [], "edges": []}


def test_default_workspace_files_are_discoverable_without_claiming_loaded(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder
    from nanobot.utils.helpers import load_bundled_template

    (tmp_path / "memory").mkdir()
    for name in ("AGENTS.md", "USER.md", "memory/MEMORY.md"):
        (tmp_path / name).write_text(load_bundled_template(name), encoding="utf-8")
    nodes = graph_from_messages(ContextBuilder(tmp_path).build_messages([], "Hello"))["nodes"]
    for name in ("AGENTS.md", "USER.md", "MEMORY.md"):
        node = next(node for node in nodes if node["name"] == name)
        assert node["state"] == "discovered"
        assert node["tokens"] == 0


def test_graph_survives_webui_history_boundary(tmp_path: Path):
    from nanobot.webui.history import fact_from_record, record_from_fact
    from nanobot.webui.transcript import _client_projection_event

    content = "Read me"
    graph = graph_from_messages([{"content": content, "_meta": source_metadata(
        content, [source_receipt(tmp_path / "guide.md", content)],
    )}])
    event = {"event": "model_request", "request_id": "request", "run_id": "run",
             "sequence": 1, "phase": "completed", "context_graph": graph}
    restored = record_from_fact(fact_from_record(event), "websocket:context-test")
    projected = _client_projection_event(restored, augment_user_media=None,
                                         augment_assistant_media=None, augment_assistant_text=None)
    assert projected["context_graph"] == graph
