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


def test_explicit_skill_provenance_in_current_message_and_history(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.loop import AgentLoop
    from nanobot.session.manager import Session

    skill = tmp_path / 'skills' / 'example'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: example\ndescription: Example\n---\n[Guide](references/guide.md)', encoding='utf-8')
    builder = ContextBuilder(tmp_path)
    block = builder.skills.build_explicit_skill_runtime_context('$example')
    assert block is not None
    current = builder.build_current_message('$example', runtime_context_blocks=[block])
    graph = graph_from_messages([current])
    nodes = {node['path']: node for node in graph['nodes']}
    assert nodes[str(skill / 'SKILL.md')]['state'] == 'loaded'
    assert nodes[str(skill / 'references/guide.md')]['state'] == 'discovered'
    assert graph['edges'] == [{'source': str(skill / 'SKILL.md'), 'target': str(skill / 'references/guide.md')}]
    session = Session(key='test:explicit-skill')
    loop = object.__new__(AgentLoop)
    loop._save_turn(session, [current], skip=0)
    assert graph_from_messages(session.get_history()) == graph


async def test_queued_skill_provenance_survives_request_and_early_persistence(tmp_path: Path):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.agent.context import TranscriptInput
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.context import RequestContext
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMResponse

    skill = tmp_path / 'skills' / 'example'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: example\ndescription: Example\n---\n[Guide](guide.md)', encoding='utf-8')
    provider = MagicMock()
    provider.get_default_model.return_value = 'test-model'
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content='Done', tool_calls=[], usage=None))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model='test-model')
    loop.tools.get_definitions = MagicMock(return_value=[])
    session = await loop.sessions.state.get('websocket:skill-provenance')
    message = InboundMessage(channel='websocket', sender_id='user', chat_id='skill-provenance', content='$example')
    runtime = loop.llm_runtime()
    request = RequestContext(channel='websocket', chat_id='skill-provenance', session_key=session.key,
                             runtime=runtime, original_user_text='$example')
    blocks = await loop._resolve_runtime_context_for_request(request, loop.tools)
    assert await loop._persist_user_message_early(message, session, runtime_context_blocks=blocks)
    persisted_graph = graph_from_messages(session.get_history())
    assert next(node for node in persisted_graph['nodes'] if node['path'] == str(skill / 'SKILL.md'))['state'] == 'loaded'

    pending = asyncio.Queue()
    await pending.put(message)
    await loop._run_agent_loop(TranscriptInput(history=[{'role': 'user', 'content': 'Initial'}], current_message=None),
                               runtime=runtime, session=session, request_context=request, pending_queue=pending)
    injected = [m for call in provider.chat_stream_with_retry.call_args_list
                for m in call.kwargs['messages'] if m.get('role') == 'user' and '$example' in str(m.get('content'))]
    assert injected
    assert graph_from_messages([injected[-1]]) == persisted_graph


def test_compacted_context_keeps_system_sources_and_counts_tools_and_summary(tmp_path: Path):
    from unittest.mock import MagicMock

    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.memory import Consolidator, MemoryStore
    from nanobot.providers.base import GenerationSettings
    from nanobot.session.manager import Session
    from nanobot.utils.llm_runtime import LLMRuntime
    from nanobot.webui.history import fact_from_record, record_from_fact
    from nanobot.webui.transcript import _client_projection_event

    (tmp_path / 'SOUL.md').write_text('Be precise.', encoding='utf-8')
    builder = ContextBuilder(tmp_path)
    provider = MagicMock()
    provider.estimate_prompt_tokens.return_value = (0, 'none')
    provider.generation = GenerationSettings(max_tokens=100)
    runtime = LLMRuntime.capture(provider, 'test', context_window_tokens=10000)
    definitions = [{'type': 'function', 'function': {'name': 'read_file', 'description': 'Read a file. ' * 80,
                    'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}}}}]
    consolidator = Consolidator(MemoryStore(tmp_path), MagicMock(), builder.build_messages, lambda: definitions)
    session = Session(key='websocket:compact-graph')
    session.add_message('user', 'Read old.md')
    session.commit_summary_checkpoint('The old file was reviewed.')
    snapshot = consolidator.context_snapshot(session, runtime=runtime)
    names = {node['name'] for node in snapshot['graph']['nodes']}
    assert {'identity.md', 'tool_contract.md', 'SOUL.md'} <= names
    without_tools = Consolidator(MemoryStore(tmp_path), MagicMock(), builder.build_messages, lambda: [])
    assert snapshot['estimated_tokens'] > without_tools.context_snapshot(session, runtime=runtime)['estimated_tokens'] > 0
    assert snapshot['context_window_tokens'] == 10000
    event = {'event': 'context_compaction', 'compaction_id': 'compact', 'phase': 'succeeded', 'context_snapshot': snapshot}
    restored = record_from_fact(fact_from_record(event), session.key)
    projected = _client_projection_event(restored, augment_user_media=None, augment_assistant_media=None, augment_assistant_text=None)
    assert projected['context_snapshot'] == snapshot


async def test_read_file_ignores_invalid_markdown_link_targets(tmp_path: Path):
    from nanobot.agent.tools.base import ToolResult
    from nanobot.agent.tools.filesystem import ReadFileTool

    path = tmp_path / "guide.md"
    path.write_text("[Invalid](foo%00.md)\n[Guide](valid.md)", encoding="utf-8")
    result = await ReadFileTool(workspace=tmp_path).execute(path=str(path))
    assert isinstance(result, ToolResult)
    assert "[Invalid](foo%00.md)" in str(result)
    assert result.context_sources[0]["links"] == [str(tmp_path / "valid.md")]


def test_image_with_explicit_skill_retains_sources_across_history(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.loop import AgentLoop
    from nanobot.session.manager import Session

    skill = tmp_path / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example\n---\n[Guide](guide.md)")
    image = tmp_path / "image.png"
    image.write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"image")
    current = ContextBuilder(tmp_path).build_current_message("$example", media=[str(image)])
    assert isinstance(current["content"], list)
    graph = graph_from_messages([current])
    assert graph["nodes"][0]["state"] == "loaded"
    assert graph["edges"] == [{"source": str(skill / "SKILL.md"), "target": str(skill / "guide.md")}]
    session = Session(key="test:image-skill")
    object.__new__(AgentLoop)._save_turn(session, [current], skip=0)
    assert graph_from_messages(session.get_history()) == graph
    current["content"][-1]["text"] = "Compacted text"
    assert graph_from_messages([current]) == {"nodes": [], "edges": []}
