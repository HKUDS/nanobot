"""Exercise passive history updates through real SDK runs and HTTP requests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from nanobot import Nanobot
from nanobot.bus.events import OutboundMessage
from nanobot.cli.gateway_runtime import _deliver_to_channel


@pytest.fixture
async def history_peer(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    peer = SimpleNamespace(
        requests=[], block_next=False, entered=asyncio.Event(), release=asyncio.Event(),
    )

    async def handle(request):
        body = await request.json()
        peer.requests.append(body)
        number = len(peer.requests)
        if peer.block_next:
            peer.block_next = False
            peer.entered.set()
            await peer.release.wait()
        if request.path.endswith("chat/completions"):
            return web.Response(
                content_type="text/event-stream",
                text='data: ' + json.dumps({
                    "id": f"chat_{number}", "object": "chat.completion.chunk",
                    "created": 1, "model": body["model"],
                    "choices": [{"index": 0, "delta": {"content": "Saved"}, "finish_reason": "stop"}],
                }) + '\n\ndata: [DONE]\n\n',
            )
        output = [
            {"type": "reasoning", "id": f"rs_{number}", "summary": [],
             "encrypted_content": f"opaque-{number}"},
            {"type": "message", "id": f"msg_{number}", "role": "assistant",
             "status": "completed", "content": [
                 {"type": "output_text", "text": "Saved", "annotations": []},
             ]},
        ]
        response = {
            "id": f"resp_{number}", "object": "response", "created_at": 1,
            "status": "completed", "model": body["model"], "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        }
        events = [
            {"type": "response.output_text.delta", "delta": "Saved"},
            {"type": "response.completed", "response": response},
        ]
        return web.Response(
            content_type="text/event-stream",
            text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        )

    app = web.Application()
    app.router.add_post("/v1/responses", handle)
    app.router.add_post("/v1/chat/completions", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    peer.url = f"http://127.0.0.1:{runner.addresses[0][1]}/v1"
    try:
        yield peer
    finally:
        peer.release.set()
        await runner.cleanup()


def _config(tmp_path, peer, api="responses"):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "providers": {"deepseek": {"apiKey": "fixture", "apiBase": peer.url}},
        "agents": {"defaults": {
            "model": "deepseek-flash", "provider": "deepseek", "maxTokens": 2048,
            "api": {"supportedApis": [api], "preferredApi": api},
        }},
    }), encoding="utf-8")
    return path


def _input_texts(body):
    texts = []
    for item in body.get("input", body.get("messages", [])):
        content = item.get("content") or []
        if isinstance(content, str):
            texts.append(content)
        else:
            texts.extend(part["text"] for part in content if "text" in part)
    return texts


@pytest.mark.parametrize("api", ["responses", "chat_completions"])
@pytest.mark.parametrize("first_run", [False, True])
async def test_ingest_replays_batches_after_restart(history_peer, tmp_path, api, first_run):
    config = _config(tmp_path, history_peer, api)
    key = "purchase:quote"
    update = "The supplier now charges $25 per box."
    async with Nanobot.from_config(config, workspace=tmp_path / "workspace") as bot:
        if first_run:
            assert (await bot.run("The supplier charges $40 per box.", session_key=key)).error is None
        for _ in range(2):
            imported = await bot.sessions.ingest(key, [{
                "role": "user", "content": update, "source": "supplier-private-source",
            }])
        exported = await bot.sessions.export(key)
        assert imported.messages[-2:] == exported.messages[-2:]
        assert exported.messages[-1]["content"] == update
        pending = (await bot._loop.sessions.state.read(key)).pending_history_replay
        assert len(pending) == 2
        assert all(batch.id not in json.dumps(exported.to_dict()) for batch in pending)

    async with Nanobot.from_config(config, workspace=tmp_path / "workspace") as bot:
        question = "What is the current price for two boxes?"
        assert (await bot.run(question, session_key=key)).error is None
        body = history_peer.requests[-1]
        texts = _input_texts(body)
        assert sum(text.count(update) for text in texts) == 2, texts
        joined = "\n".join(texts)
        assert joined.rindex(update) < joined.index(question)
        assert "supplier-private-source" not in json.dumps(body)
        if api == "responses" and first_run:
            assert any(item.get("encrypted_content") == "opaque-1" for item in body["input"])
        assert (await bot.run("Confirm the price.", session_key=key)).error is None
        assert sum(text.count(update) for text in _input_texts(history_peer.requests[-1])) == 2


@pytest.mark.parametrize("first_run", [False, True])
async def test_delivery_during_model_call_survives_checkpoints(history_peer, tmp_path, first_run):
    config = _config(tmp_path, history_peer)
    key = "telegram:quote"
    async with Nanobot.from_config(config, workspace=tmp_path / "workspace") as bot:
        if first_run:
            assert (await bot.run("The supplier charges $40.", session_key=key)).error is None
        history_peer.block_next = True
        running = asyncio.create_task(bot.run("Check the supplier.", session_key=key))
        try:
            await asyncio.wait_for(history_peer.entered.wait(), timeout=10)
            sessions = bot._loop.sessions
            generation = (await sessions.state.get_header(key)).generation
            await _deliver_to_channel(
                OutboundMessage(channel="telegram", chat_id="quote", content="Heartbeat: quote is $25."),
                bus=bot._loop.bus, session_manager=sessions, record=True,
                session_key=key, session_generation=generation,
            )
            assert "Heartbeat: quote is $25." not in _input_texts(history_peer.requests[-1])
        finally:
            history_peer.release.set()
            result = await running
        assert result.error is None
        assert (await bot.run("What did the notification say?", session_key=key)).error is None
        texts = _input_texts(history_peer.requests[-1])
        assert texts.count("Heartbeat: quote is $25.") == 1
        joined = "\n".join(texts)
        assert joined.index("Heartbeat: quote is $25.") < joined.index("What did the notification say?")
        assert (await bot.run("Confirm.", session_key=key)).error is None
        assert _input_texts(history_peer.requests[-1]).count("Heartbeat: quote is $25.") == 1


async def test_staged_ingest_survives_interrupted_request(history_peer, tmp_path):
    config = _config(tmp_path, history_peer)
    key = "purchase:interrupted"
    update = "The supplier now charges $25."
    async with Nanobot.from_config(config, workspace=tmp_path / "workspace") as bot:
        await bot.run("The supplier charges $40.", session_key=key)
        await bot.sessions.ingest(key, [{"role": "user", "content": update}])
        history_peer.block_next = True
        running = await bot.run_streamed("What is the total?", session_key=key)
        try:
            await asyncio.wait_for(history_peer.entered.wait(), timeout=10)
            stored = await bot._loop.sessions.state.read(key)
            assert stored.pending_history_replay == []
            assert sum(message["content"].count(update) for message in stored.provider_state.pending_messages) == 1
        finally:
            await running.cancel()
            history_peer.release.set()
    async with Nanobot.from_config(config, workspace=tmp_path / "workspace") as bot:
        assert (await bot.run("Retry the calculation.", session_key=key)).error is None
        assert sum(text.count(update) for text in _input_texts(history_peer.requests[-1])) == 1


async def test_ingested_tools_and_media_use_canonical_projection(history_peer, tmp_path):
    config = _config(tmp_path, history_peer)
    async with Nanobot.from_config(config, workspace=tmp_path / "workspace") as bot:
        key = "purchase:tools"
        await bot.run("Read supplier updates.", session_key=key)
        await bot.sessions.ingest(key, [
            {"role": "assistant", "content": "[Message Time: yesterday]\nSupplier update.",
             "tool_calls": [{"id": "imported_call", "type": "function", "function": {
                 "name": "read_file", "arguments": '{"path":"quote.txt"}',
             }}]},
            {"role": "tool", "tool_call_id": "imported_call", "content": "$25 per box"},
            {"role": "user", "content": "", "media": ["/supplier/quote.png"]},
        ])
        assert (await bot.run("Calculate two boxes.", session_key=key)).error is None
        body = history_peer.requests[-1]
        assert any(item.get("encrypted_content") == "opaque-1" for item in body["input"])
        calls = [item for item in body["input"] if item.get("type") == "function_call"]
        assert [item["call_id"] for item in calls] == ["imported_call"]
        outputs = [item for item in body["input"] if item.get("type") == "function_call_output"]
        assert outputs == [{"type": "function_call_output", "call_id": "imported_call", "output": "$25 per box"}]
        texts = "\n".join(_input_texts(body))
        assert "Supplier update." in texts
        assert "[Message Time:" not in texts
        assert "[image: /supplier/quote.png]" in texts
