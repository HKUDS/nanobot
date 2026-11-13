from __future__ import annotations

import base64
import copy
import io
import json
import random
from types import SimpleNamespace

import pytest
from aiohttp import web
from PIL import Image

from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import LLMProvider, ProviderCallContext
from nanobot.providers.bedrock_provider import BedrockProvider
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.github_copilot_provider import GitHubCopilotProvider
from nanobot.providers.images import (
    INLINE_IMAGE_BYTE_BUDGET,
    image_input_ids,
    prepare_inline_images,
    state_image_input_ids,
)
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.openai_responses import ResponsesBackend
from nanobot.providers.registry import ModelAPICapabilities, find_by_name
from nanobot.providers.xai_grok_provider import XAIGrokProvider


@pytest.fixture(scope="module")
def image_blocks():
    noise = random.Random(234).randbytes(900 * 1800)
    screenshot = Image.frombytes("L", (900, 1800), noise).point(lambda x: 240 + x // 16)
    jpeg = io.BytesIO()
    screenshot.save(jpeg, "JPEG", quality=95)
    transparent = io.BytesIO()
    Image.new("RGBA", (700, 700), (20, 60, 100, 80)).save(transparent, "PNG", compress_level=0)
    thumbnail = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(thumbnail, "JPEG", quality=95)
    images = [("jpeg", jpeg.getvalue())] * 3 + [("png", transparent.getvalue()), ("jpeg", thumbnail.getvalue())]
    return [
        {"type": "image_url", "image_url": {
            "url": f"data:image/{mime};base64,{base64.b64encode(raw).decode()}",
        }}
        for mime, raw in images
    ]


def _messages(blocks):
    return [{"role": "user", "content": [{"type": "text", "text": "Read these images."}, *blocks]}]


@pytest.fixture
async def image_peer(monkeypatch):
    requests = []
    reject = {"images": False, "unavailable": False}

    def response_events(body):
        output = [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": "answer", "annotations": []}]}]
        response = {
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "status": "completed", "model": body["model"], "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        return response, [
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.output_item.done", "output_index": 0, "item": output[0]},
            {"type": "response.completed", "response": response},
        ]

    async def handle_websocket(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            body = json.loads(message.data)
            requests.append((request.path, body))
            if reject["unavailable"]:
                await socket.send_json({"type": "error", "status": 503, "error": {
                    "message": "Temporarily unavailable",
                }})
                continue
            _, events = response_events(body)
            for event in events:
                await socket.send_json(event)
        return socket

    async def handle(request):
        body = await request.json()
        requests.append((request.path, body))
        if request.path.endswith("responses"):
            if reject["unavailable"]:
                return web.json_response({"error": {"message": "Temporarily unavailable"}}, status=503)
            has_images = "input_image" in json.dumps(body["input"])
            if reject["images"] and has_images:
                return web.json_response({"error": {
                    "type": "invalid_request_error", "code": "unsupported_image",
                    "message": "This Responses API does not support input_image.",
                }}, status=400)
            response, events = response_events(body)
        elif request.path.endswith("messages"):
            response = {
                "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                "content": [{"type": "text", "text": "answer"}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            events = [
                {"type": "message_start", "message": {**response, "content": [], "stop_reason": None}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "answer"}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                 "usage": {"output_tokens": 5}},
                {"type": "message_stop"},
            ]
        else:
            response = {
                "id": "chat_1", "object": "chat.completion", "created": 1, "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
            events = [{
                "id": "chat_1", "object": "chat.completion.chunk", "created": 1, "model": body["model"],
                "choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": "stop"}],
            }]
        if not body.get("stream"):
            return web.json_response(response)
        data = "".join(f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n" for event in events)
        return web.Response(text=data, content_type="text/event-stream")

    async def token(_request):
        return web.json_response({"token": "copilot-fixture", "expires_at": 4_000_000_000})

    app = web.Application(client_max_size=16 * 1024 * 1024)
    app.router.add_post("/{path:.*}", handle)
    app.router.add_get("/v1/responses", handle_websocket)
    app.router.add_get("/copilot_token", token)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}", requests, reject
    finally:
        await runner.cleanup()


def _provider(adapter, url, monkeypatch):
    if adapter == "azure":
        return AzureOpenAIProvider(api_key="fixture", api_base=url, default_model="gpt-5.4")
    if adapter == "anthropic":
        return AnthropicProvider(api_key="fixture", api_base=url)
    if adapter == "copilot":
        monkeypatch.setenv("NANOBOT_COPILOT_BASE_URL", f"{url}/v1")
        monkeypatch.setenv("NANOBOT_COPILOT_TOKEN_URL", f"{url}/copilot_token")
        monkeypatch.setattr("nanobot.providers.github_copilot_provider._load_github_token",
                            lambda: SimpleNamespace(access="github-fixture"))
        return GitHubCopilotProvider(default_model="github-copilot/gpt-5.4-mini")
    if adapter in {"codex", "codex_ws"}:
        monkeypatch.setattr("nanobot.providers.openai_codex_provider.DEFAULT_CODEX_URL", f"{url}/v1/responses")
        monkeypatch.setattr("nanobot.providers.openai_codex_provider.get_codex_token",
                            lambda **_: SimpleNamespace(account_id="fixture", access="codex-fixture"))
        return OpenAICodexProvider(default_model="openai-codex/gpt-5.4")
    if adapter == "xai":
        monkeypatch.setattr("nanobot.providers.xai_grok_provider.DEFAULT_XAI_GROK_URL", f"{url}/v1/responses")
        monkeypatch.setattr("nanobot.providers.xai_grok_provider.get_xai_oauth_token",
                            lambda **_: SimpleNamespace(access="xai-fixture"))
        return XAIGrokProvider(extra_body={"tools": []})
    spec = find_by_name("deepseek" if adapter == "deepseek" else "openai")
    return OpenAICompatProvider(
        api_key="fixture", api_base=f"{url}/v1", spec=spec,
        default_model="deepseek-v4-flash-vision-exp" if adapter == "deepseek" else "gpt-5.4",
        model_api=ModelAPICapabilities(("chat_completions",), "chat_completions") if adapter == "chat"
        else ModelAPICapabilities(("responses",), "responses") if adapter != "deepseek" else None,
        extra_body={"tools": []},
    )


def _received_images(body):
    images = []
    for item in body.get("input", body.get("messages", [])):
        content = item.get("output") if item.get("type") == "function_call_output" else item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block["type"] == "input_image":
                images.append(base64.b64decode(block["image_url"].split(",", 1)[1]))
            elif block["type"] == "image_url":
                images.append(base64.b64decode(block["image_url"]["url"].split(",", 1)[1]))
            elif block["type"] == "image":
                images.append(base64.b64decode(block["source"]["data"]))
    return images


def _assert_prepared(images, blocks):
    assert len(images) == 5
    assert sum(4 * ((len(raw) + 2) // 3) + len("data:image/jpeg;base64,") for raw in images) <= 1_000_000
    for raw in images[:3]:
        with Image.open(io.BytesIO(raw)) as image:
            assert image.size == (900, 1800)
    with Image.open(io.BytesIO(images[3])) as image:
        assert image.mode == "RGBA"
        assert image.size == (700, 700)
        assert image.getpixel((0, 0)) == (20, 60, 100, 80)
    assert images[4] == base64.b64decode(blocks[4]["image_url"]["url"].split(",", 1)[1])


@pytest.mark.parametrize("adapter", ["openai", "azure", "deepseek", "copilot", "xai", "chat", "anthropic"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_providers_prepare_image_copies(image_peer, image_blocks, monkeypatch, adapter, streaming):
    url, requests, _ = image_peer
    provider = _provider(adapter, url, monkeypatch)
    messages = _messages(image_blocks)
    original = json.dumps(messages)
    try:
        call = provider.chat_stream if streaming else provider.chat
        result = await call(messages)
        assert result.content == "answer"
        assert result.finish_reason == "stop"
        assert len(requests) == 1
        _assert_prepared(_received_images(requests[0][1]), image_blocks)
        assert json.dumps(messages) == original
    finally:
        await provider.aclose()


@pytest.mark.parametrize("streaming", [False, True])
async def test_bedrock_prepares_images_before_native_conversion(image_blocks, streaming):
    class Client:
        requests = []

        def converse(self, **body):
            self.requests.append(body)
            return {"output": {"message": {"content": [{"text": "answer"}]}}, "stopReason": "end_turn"}

        def converse_stream(self, **body):
            self.requests.append(body)
            return {"stream": iter([
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "answer"}}},
                {"messageStop": {"stopReason": "end_turn"}},
            ])}

    client = Client()
    provider = BedrockProvider(client=client)
    messages = _messages(image_blocks)
    original = json.dumps(messages)
    result = await (provider.chat_stream if streaming else provider.chat)(messages)
    assert result.content == "answer"
    images = [block["image"]["source"]["bytes"] for message in client.requests[0]["messages"]
              for block in message["content"] if "image" in block]
    _assert_prepared(images, image_blocks)
    assert json.dumps(messages) == original


@pytest.mark.parametrize("streaming", [False, True])
async def test_responses_image_rejection_preserves_input_and_replay(
    image_peer, image_blocks, monkeypatch, streaming,
):
    url, requests, reject = image_peer
    provider = _provider("azure", url, monkeypatch)
    messages = _messages(image_blocks)
    try:
        first = await provider.chat(messages)
        assert first.provider_state is not None
        pending = {"role": "user", "content": "Continue."}
        messages.extend([{"role": "assistant", "content": first.content}, pending])
        reject["images"] = True
        original = copy.deepcopy(messages)
        state = first.provider_state.with_pending_messages([pending])
        original_state = state.to_private_record()
        call = provider.chat_stream_with_retry if streaming else provider.chat_with_retry
        result = await call(messages, provider_context=ProviderCallContext(
            session_id="image-rejection", conversation_state=state,
        ))
        assert result.finish_reason == "error"
        assert result.error_status_code == 400
        assert result.error_code == "unsupported_image"
        assert len(requests) == 2
        assert "input_image" in json.dumps(requests[1][1]["input"])
        assert messages == original
        assert state.to_private_record() == original_state
    finally:
        await provider.aclose()


@pytest.mark.parametrize("streaming", [False, True])
async def test_auto_responses_fallback_keeps_prepared_images(image_peer, image_blocks, monkeypatch, streaming):
    url, requests, reject = image_peer
    provider = _provider("deepseek", url, monkeypatch)
    reject["images"] = True
    try:
        result = await (provider.chat_stream if streaming else provider.chat)(_messages(image_blocks))
        assert result.content == "answer"
        assert [path for path, _ in requests] == ["/v1/responses", "/v1/chat/completions"]
        for _, body in requests:
            _assert_prepared(_received_images(body), image_blocks)
    finally:
        await provider.aclose()


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("api", ["chat_completions", "responses"])
async def test_text_only_model_rejects_images_explicitly(image_peer, image_blocks, streaming, api):
    url, requests, _ = image_peer
    provider = OpenAICompatProvider(
        api_key="fixture", api_base=f"{url}/v1", spec=find_by_name("deepseek"),
        default_model="deepseek-v4-pro", extra_body={"tools": []},
        model_api=ModelAPICapabilities((api,), api),
    )
    messages = _messages(image_blocks)
    original = copy.deepcopy(messages)
    try:
        call = provider.chat_stream_with_retry if streaming else provider.chat_with_retry
        result = await call(messages)
        assert result.finish_reason == "error"
        assert result.error_kind == "invalid_request"
        assert result.error_should_retry is False
        assert result.content == "The selected model does not support image input. Select an image-capable model and retry."
        assert requests == []
        assert messages == original
        assert not LLMProvider.is_transient_response(result)
    finally:
        await provider.aclose()


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("api", ["chat_completions", "responses"])
async def test_unknown_deepseek_model_preserves_images(image_peer, image_blocks, streaming, api):
    url, requests, _ = image_peer
    provider = OpenAICompatProvider(
        api_key="fixture", api_base=f"{url}/v1", spec=find_by_name("deepseek"),
        default_model="deepseek-custom-model", extra_body={"tools": []},
        model_api=ModelAPICapabilities((api,), api),
    )
    messages = _messages(image_blocks)
    original = copy.deepcopy(messages)
    try:
        call = provider.chat_stream_with_retry if streaming else provider.chat_with_retry
        result = await call(messages)
        assert result.content == "answer"
        assert len(requests) == 1
        _assert_prepared(_received_images(requests[0][1]), image_blocks)
        assert messages == original
    finally:
        await provider.aclose()


@pytest.mark.parametrize("adapter,streaming", [
    ("azure", False), ("azure", True), ("codex", True), ("codex_ws", True),
])
async def test_prepared_native_images_keep_identity_for_replay_and_cross_provider_fallback(
    image_peer, image_blocks, monkeypatch, adapter, streaming,
):
    url, requests, reject = image_peer
    primary = _provider(adapter, url, monkeypatch)
    messages = _messages(image_blocks)
    original = copy.deepcopy(messages)
    original_ids = image_input_ids(messages)
    session_id = "image-identity" if adapter == "codex_ws" else None
    traces = []
    if adapter.startswith("codex"):
        import nanobot.providers.openai_codex_provider as codex

        start_trace = codex._start_codex_langfuse_generation

        def capture_trace(**kwargs):
            traces.append(copy.deepcopy(kwargs["body"]))
            return start_trace(**kwargs)

        monkeypatch.setattr(codex, "_start_codex_langfuse_generation", capture_trace)
    try:
        call = primary.chat_stream_with_context if streaming else primary.chat_with_context
        first = await call(messages=messages, provider_context=ProviderCallContext(session_id=session_id))
        assert first.provider_state is not None
        assert state_image_input_ids(first.provider_state) == original_ids
        first_wire = requests[0][1]
        # Real transport preparation changed the URLs, not the logical image inputs.
        assert image_input_ids(first_wire) != original_ids
        assert _received_images({"input": first.provider_state.payload["items"]}) == _received_images(first_wire)

        pending = {"role": "user", "content": "Continue."}
        messages.extend([{"role": "assistant", "content": first.content}, pending])
        state = first.provider_state.with_pending_messages([pending])
        before = state.to_private_record()
        call = primary.chat_stream_with_context if streaming else primary.chat_with_context
        replay = await call(messages=messages, provider_context=ProviderCallContext(
            session_id=session_id, conversation_state=state,
        ))
        assert replay.provider_state is not None
        assert state_image_input_ids(replay.provider_state) == original_ids
        if session_id:
            assert requests[1][1]["previous_response_id"] == "resp_1"
            assert _received_images(requests[1][1]) == []
        else:
            assert _received_images(requests[1][1]) == _received_images(first_wire)
        assert "_meta" not in json.dumps(requests[1][1])
        if traces:
            assert _received_images(traces[1]) == _received_images(first_wire)
            assert all("_meta" not in json.dumps(trace) for trace in traces)
        assert state.to_private_record() == before

        reject["unavailable"] = True
        fallback = FallbackProvider(
            primary, [ModelPresetConfig(model="gpt-5.4", provider="custom")],
            provider_factory=lambda _: _provider("chat", url, monkeypatch),
        )
        call = fallback.chat_stream_with_context if streaming else fallback.chat_with_context
        result = await call(messages=messages, provider_context=ProviderCallContext(
            session_id=session_id, conversation_state=replay.provider_state,
        ))
        assert result.content == "answer"
        assert result.is_fallback
        assert requests[-1][0] == "/v1/chat/completions"
        _assert_prepared(_received_images(requests[-1][1]), image_blocks)
        assert "_meta" not in json.dumps(requests[-1][1])
        assert messages[:1] == original
    finally:
        await primary.aclose()


async def test_sse_backend_keeps_original_identity_after_preparing_and_replaying_images(image_peer, image_blocks):
    url, requests, _ = image_peer
    backend = ResponsesBackend()
    messages = _messages(image_blocks)
    original_ids = image_input_ids(messages)
    state = None
    for _ in range(2):
        body = backend.prepare(messages, provider="fixture", model="fixture", state=state).body
        body["stream"] = True
        before = copy.deepcopy(body)
        result = await backend.sse_request(
            f"{url}/v1/responses", {}, body, provider="fixture",
            error_factory=lambda status, _headers, _raw: RuntimeError(f"HTTP {status}"),
        )
        assert result.provider_state is not None
        assert state_image_input_ids(result.provider_state) == original_ids
        assert "_meta" not in json.dumps(requests[-1][1])
        assert image_input_ids(requests[-1][1]) != original_ids
        assert body == before
        state = result.provider_state
    assert _received_images(requests[0][1]) == _received_images(requests[1][1])


async def test_codex_sse_keeps_identity_when_prepared_image_remains_above_soft_budget(image_peer, monkeypatch):
    url, requests, reject = image_peer
    output = io.BytesIO()
    with Image.frombytes("RGB", (1400, 1400), random.Random(442).randbytes(1400 * 1400 * 3)) as image:
        image.save(output, "PNG")
    messages = _messages([{"type": "image_url", "image_url": {
        "url": f"data:image/png;base64,{base64.b64encode(output.getvalue()).decode()}",
    }}])
    original_ids = image_input_ids(messages)
    prepared = await prepare_inline_images({"messages": messages})
    assert len(prepared["messages"][0]["content"][1]["image_url"]["url"]) > INLINE_IMAGE_BYTE_BUDGET
    primary = _provider("codex", url, monkeypatch)
    try:
        response = await primary.chat_stream_with_context(messages=messages, provider_context=ProviderCallContext())
        assert response.provider_state is not None
        assert state_image_input_ids(response.provider_state) == original_ids
        assert image_input_ids(requests[0][1]) == image_input_ids(prepared)
        assert "_meta" not in json.dumps(requests[0][1])
        reject["unavailable"] = True
        fallback = FallbackProvider(
            primary, [ModelPresetConfig(model="gpt-5.4", provider="custom")],
            provider_factory=lambda _: _provider("chat", url, monkeypatch),
        )
        result = await fallback.chat_stream_with_context(messages=messages, provider_context=ProviderCallContext(
            conversation_state=response.provider_state,
        ))
        assert result.content == "answer"
        assert result.is_fallback
        assert requests[-1][0] == "/v1/chat/completions"
    finally:
        await primary.aclose()
