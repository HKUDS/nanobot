"""Exercise inline image preparation at provider SDK and HTTP boundaries."""

from __future__ import annotations

import base64
import io
import json
import random
from types import SimpleNamespace

import pytest
from aiohttp import web
from PIL import Image

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import ProviderCallContext
from nanobot.providers.bedrock_provider import BedrockProvider
from nanobot.providers.github_copilot_provider import GitHubCopilotProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name
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
    reject = {"images": False, "text": False}

    async def handle(request):
        body = await request.json()
        requests.append((request.path, body))
        if request.path.endswith("responses"):
            has_images = "input_image" in json.dumps(body["input"])
            if reject["images"] and (has_images or reject["text"]):
                return web.json_response({"error": {
                    "type": "invalid_request_error", "code": "unsupported_image",
                    "message": "This Responses API does not support input_image.",
                }}, status=400)
            output = [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "answer", "annotations": []}]}]
            response = {
                "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
                "status": "completed", "model": body["model"], "output": output,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }
            events = [
                {"type": "response.output_text.delta", "delta": "answer"},
                {"type": "response.output_item.done", "output_index": 0, "item": output[0]},
                {"type": "response.completed", "response": response},
            ]
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


def _provider(adapter, url, monkeypatch, api_type=None):
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
    if adapter == "xai":
        monkeypatch.setattr("nanobot.providers.xai_grok_provider.DEFAULT_XAI_GROK_URL", f"{url}/v1/responses")
        monkeypatch.setattr("nanobot.providers.xai_grok_provider.get_xai_oauth_token",
                            lambda **_: SimpleNamespace(access="xai-fixture"))
        return XAIGrokProvider(extra_body={"tools": []})
    spec = find_by_name("deepseek" if adapter == "deepseek" else "openai")
    return OpenAICompatProvider(
        api_key="fixture", api_base=f"{url}/v1", spec=spec,
        default_model="deepseek-v4-flash-vision-exp" if adapter == "deepseek" else "gpt-5.4",
        api_type=api_type or ("chat_completions" if adapter == "chat" else "responses"), extra_body={"tools": []},
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
@pytest.mark.parametrize("reject_text", [False, True])
async def test_responses_image_rejection_discards_replay_and_retries_once(
    image_peer, image_blocks, monkeypatch, streaming, reject_text,
):
    url, requests, reject = image_peer
    provider = _provider("azure", url, monkeypatch)
    messages = _messages(image_blocks)
    try:
        first = await provider.chat(messages)
        assert first.provider_state is not None
        pending = {"role": "user", "content": "Continue."}
        messages.extend([{"role": "assistant", "content": first.content}, pending])
        reject.update(images=True, text=reject_text)
        call = provider.chat_stream_with_retry if streaming else provider.chat_with_retry
        result = await call(messages, provider_context=ProviderCallContext(
            session_id="image-rejection", conversation_state=first.provider_state.with_pending_messages([pending]),
        ))
        assert result.finish_reason == ("error" if reject_text else "stop")
        assert len(requests) == 3
        assert "input_image" in json.dumps(requests[1][1]["input"])
        assert "input_image" not in json.dumps(requests[2][1]["input"])
        assert "not delivered to model" in json.dumps(requests[2][1]["input"])
    finally:
        await provider.aclose()


@pytest.mark.parametrize("streaming", [False, True])
async def test_auto_responses_fallback_keeps_prepared_images(image_peer, image_blocks, monkeypatch, streaming):
    url, requests, reject = image_peer
    provider = _provider("deepseek", url, monkeypatch, api_type="auto")
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
async def test_text_only_model_keeps_its_image_policy(image_peer, image_blocks, streaming):
    url, requests, _ = image_peer
    provider = OpenAICompatProvider(
        api_key="fixture", api_base=f"{url}/v1", spec=find_by_name("deepseek"),
        default_model="deepseek-v4-flash", api_type="responses", extra_body={"tools": []},
    )
    try:
        result = await (provider.chat_stream if streaming else provider.chat)(_messages(image_blocks))
        assert result.content == "answer"
        assert "input_image" not in json.dumps(requests[0][1])
        assert "data:image/" not in json.dumps(requests[0][1])
        assert "Read these images." in json.dumps(requests[0][1])
    finally:
        await provider.aclose()
