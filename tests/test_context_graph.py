from pathlib import Path

import pytest

from nanobot.context_graph import graph_from_sources
from nanobot.context_sources import PromptSourcesEvent, capture_sources
from nanobot.file_references import source_receipt


def graph_from_observations(sources):
    return graph_from_sources([source_receipt(source.path, source.content, loaded=source.loaded) for source in sources])


def graph_from_build(build):
    with capture_sources() as sources:
        build()
    return graph_from_observations(sources)


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
    graph = graph_from_sources([source])
    assert [node["state"] for node in graph["nodes"]] == ["loaded", "discovered", "discovered"]


def test_repeated_source_analysis_resolves_links_in_the_current_directory(tmp_path: Path):
    content = "[Guide](guide.md)"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    link = first / "guide.md"
    try:
        link.symlink_to(tmp_path / "original.md")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise
    assert source_receipt(first / "SKILL.md", content)["links"] == [str(tmp_path / "original.md")]
    assert source_receipt(second / "SKILL.md", content)["links"] == [str(second / "guide.md")]
    link.unlink()
    link.symlink_to(tmp_path / "replacement.md")
    assert source_receipt(first / "SKILL.md", content)["links"] == [str(tmp_path / "replacement.md")]
    assert source_receipt(first / "SKILL.md", "[New](new.md)")["links"] == [str(first / "new.md")]


def test_source_token_estimate_updates_when_tokenizer_becomes_available(tmp_path: Path, monkeypatch):
    import tiktoken

    import nanobot.file_references as context_graph

    content = "Hello world"
    monkeypatch.setattr(context_graph, "get_token_encoding", lambda: None)
    assert source_receipt(tmp_path / "source.txt", content)["tokens"] == len(content.encode())
    encoding = tiktoken.get_encoding("cl100k_base")
    monkeypatch.setattr(context_graph, "get_token_encoding", lambda: encoding)
    assert source_receipt(tmp_path / "source.txt", content)["tokens"] == len(encoding.encode_ordinary(content))


@pytest.mark.asyncio
async def test_prompt_working_set_reuses_analysis_and_invalidates_changed_content(tmp_path: Path, monkeypatch):
    from nanobot.context_sources import PromptSource
    from nanobot.file_references import MarkdownReferences
    from nanobot.webui.context_observer import ContextGraphObserver

    calls = []
    original = MarkdownReferences.references

    def references(self, content):
        calls.append(content)
        yield from original(self, content)

    monkeypatch.setattr(MarkdownReferences, "references", references)
    sources = tuple(PromptSource(tmp_path / f"{index}.md", f"{tmp_path} source {index}\n[Guide](guide.md)\n" + "text " * 1600)
                    for index in range(20))
    observer = ContextGraphObserver(None)
    await observer.observe_prompt("chat", sources, {}, persistent=False)
    await observer.observe_prompt("chat", sources, {}, persistent=False)
    assert len(calls) == 20
    moved = tuple(PromptSource(tmp_path / "other" / source.path.name, source.content) for source in sources)
    await observer.observe_prompt("other-chat", moved, {}, persistent=False)
    assert len(calls) == 20
    graph = await observer.snapshot("other-chat", {}, persistent=False)
    assert str(tmp_path / "other" / "guide.md") in {node["path"] for node in graph["nodes"]}
    changed = (PromptSource(sources[0].path, f"{tmp_path}\n[New](new.md)"), *sources[1:])
    await observer.observe_prompt("chat", changed, {}, persistent=False)
    assert len(calls) == 21
    graph = await observer.snapshot("chat", {}, persistent=False)
    assert str(tmp_path / "new.md") in {node["path"] for node in graph["nodes"]}


def test_source_analysis_evicts_by_budget_and_preserves_recent_results(tmp_path: Path, monkeypatch):
    from collections import OrderedDict

    import nanobot.file_references as references

    calls = []

    class Parser:
        def references(self, content):
            calls.append(content)
            yield content.strip() + ".md"

    monkeypatch.setattr(references, "_analysis_cache", OrderedDict())
    monkeypatch.setattr(references, "_analysis_bytes", 0)
    monkeypatch.setattr(references, "_ANALYSIS_SOURCE_BYTES", 120)
    monkeypatch.setitem(references.REFERENCE_PARSERS, ".budget", Parser())
    source = tmp_path / "source.budget"
    first, second, third = (name.ljust(60) for name in ("first", "second", "third"))
    for content in (first, second, first, third, first):
        assert source_receipt(source, content)["links"] == [str(tmp_path / (content.strip() + ".md"))]
    assert calls == [first, second, third]
    source_receipt(source, second)
    assert calls == [first, second, third, second]


def test_system_sources_track_actual_injection_and_skill_metadata(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder

    (tmp_path / "SOUL.md").write_text("Be precise", encoding="utf-8")
    skill = tmp_path / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example\n---\n[Reference](ref.md)", encoding="utf-8")
    graph = graph_from_build(lambda: ContextBuilder(tmp_path).build_messages([], "Hello"))
    by_path = {node["path"]: node for node in graph["nodes"]}
    assert by_path[str(tmp_path / "SOUL.md")]["state"] == "loaded"
    assert by_path[str(skill / "SKILL.md")]["state"] == "discovered"
    assert str(skill / "ref.md") not in by_path


def test_default_workspace_files_are_discoverable_without_claiming_loaded(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder
    from nanobot.utils.helpers import load_bundled_template

    (tmp_path / "memory").mkdir()
    for name in ("AGENTS.md", "USER.md", "memory/MEMORY.md"):
        (tmp_path / name).write_text(load_bundled_template(name), encoding="utf-8")
    nodes = graph_from_build(lambda: ContextBuilder(tmp_path).build_messages([], "Hello"))["nodes"]
    for name in ("AGENTS.md", "USER.md", "MEMORY.md"):
        node = next(node for node in nodes if node["name"] == name)
        assert node["state"] == "discovered"
        assert node["tokens"] == 0


def test_graph_survives_webui_history_boundary(tmp_path: Path):
    from nanobot.webui.history import fact_from_record, record_from_fact
    from nanobot.webui.transcript import _client_projection_event

    content = "Read me"
    graph = graph_from_sources([source_receipt(tmp_path / "guide.md", content)])
    event = {"event": "model_request", "request_id": "request", "run_id": "run",
             "sequence": 1, "phase": "completed", "context_graph": graph}
    restored = record_from_fact(fact_from_record(event), "websocket:context-test")
    projected = _client_projection_event(restored, augment_user_media=None,
                                         augment_assistant_media=None, augment_assistant_text=None)
    assert projected["context_graph"] == graph


def test_explicit_skill_sources_in_current_message(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder

    skill = tmp_path / 'skills' / 'example'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: example\ndescription: Example\n---\n[Guide](references/guide.md)', encoding='utf-8')
    builder = ContextBuilder(tmp_path)
    block = builder.skills.build_explicit_skill_runtime_context('$example')
    assert block is not None
    graph = graph_from_build(lambda: builder.build_current_message('$example', runtime_context_blocks=[block]))
    nodes = {node['path']: node for node in graph['nodes']}
    assert nodes[str(skill / 'SKILL.md')]['state'] == 'loaded'
    assert nodes[str(skill / 'references/guide.md')]['state'] == 'discovered'
    assert graph['edges'] == [{'source': str(skill / 'SKILL.md'), 'target': str(skill / 'references/guide.md')}]


async def test_queued_skill_sources_reach_the_request(tmp_path: Path):
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
    expected_path = str(skill / 'SKILL.md')
    from nanobot.events import EventSink
    from nanobot.webui.context_source_hook import create_context_source_hook
    events = []
    async def publish(event):
        events.append(event)

    pending = asyncio.Queue()
    await pending.put(message)
    await loop._run_agent_loop(TranscriptInput(history=[{'role': 'user', 'content': 'Initial'}], current_message=None),
                               runtime=runtime, session=session, request_context=request, pending_queue=pending,
                               events=EventSink(publish), hook_factories=[create_context_source_hook])
    injected = [m for call in provider.chat_stream_with_retry.call_args_list
                for m in call.kwargs['messages'] if m.get('role') == 'user' and '$example' in str(m.get('content'))]
    assert injected
    graph = graph_from_observations([source for event in events if isinstance(event, PromptSourcesEvent) for source in event.sources])
    assert any(node['path'] == expected_path and node['state'] == 'loaded' for node in graph['nodes'])
    assert {'source': expected_path, 'target': str(skill / 'guide.md')} in graph['edges']


async def test_read_file_ignores_invalid_markdown_link_targets(tmp_path: Path):
    from nanobot.agent.tools.filesystem import ReadFileTool
    from nanobot.webui.context_observer import read_source

    path = tmp_path / "guide.md"
    path.write_text("[Invalid](foo%00.md)\n[Guide](valid.md)", encoding="utf-8")
    result = await ReadFileTool(workspace=tmp_path).execute(path=str(path))
    assert "[Invalid](foo%00.md)" in str(result)
    source = read_source({"name": "read_file", "phase": "end", "arguments": {"path": str(path)}, "result": result})
    assert source["links"] == [str(tmp_path / "valid.md")]


def test_image_with_explicit_skill_reports_sources(tmp_path: Path):
    from nanobot.agent.context import ContextBuilder

    skill = tmp_path / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: example\ndescription: Example\n---\n[Guide](guide.md)")
    image = tmp_path / "image.png"
    image.write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"image")
    with capture_sources() as sources:
        current = ContextBuilder(tmp_path).build_current_message("$example", media=[str(image)])
    assert isinstance(current["content"], list)
    graph = graph_from_observations(sources)
    assert graph["nodes"][0]["state"] == "loaded"
    assert graph["edges"] == [{"source": str(skill / "SKILL.md"), "target": str(skill / "guide.md")}]
