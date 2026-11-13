from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import BadRequestError
from openai.types.chat import ChatCompletionChunk

from nanobot.providers.base import ProviderCallContext
from nanobot.providers.images import image_input_ids
from nanobot.providers.model_api import ModelAPICapabilities
from nanobot.providers.openai_compat_provider import (
    _RESPONSES_FAILURE_THRESHOLD,
    OpenAICompatProvider,
)
from nanobot.providers.openai_responses.state import build_responses_state
from nanobot.providers.registry import find_by_name

_MODEL = "gpt-5-chat"
_IMAGES = [
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,Zmlyc3Q="}},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,c2Vjb25k"}},
]


@pytest.fixture()
def provider():
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as sdk:
        client = sdk.return_value
        client.responses.create = AsyncMock()

        async def create_chat(**kwargs):
            return _ChatStream() if kwargs.get("stream") else {
                "choices": [{"message": {"content": "Both images received."}, "finish_reason": "stop"}],
            }

        client.chat.completions.create = AsyncMock(side_effect=create_chat)
        yield OpenAICompatProvider(
            api_key="fixture", default_model=_MODEL, spec=find_by_name("openai"),
        ), client


def _context(provider, *, recovery=False):
    state = build_responses_state(
        provider=provider._responses_state_provider(), model=_MODEL,
        input_items=[{
            "type": "message", "role": "user",
            "content": [{"type": "input_image", "image_url": _IMAGES[0]["image_url"]["url"]}],
        }],
        output_items=[{
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "First image received."}],
        }],
    ).with_pending_messages([{
        "role": "user", "content": [*_IMAGES[1:], {"type": "text", "text": "Compare the images."}],
    }])
    return ProviderCallContext(
        conversation_state=state,
        # Recovery can require only the latest image, but a Chat downgrade must
        # also retain the earlier image represented by the native prefix.
        required_image_inputs=image_input_ids(_IMAGES[1:]) if recovery else (),
    )


def _messages(public_images):
    return [
        {"role": "user", "content": (
            [_IMAGES[0]] if public_images in {"complete", "prefix_only"} else "[image: first.png]"
        )},
        {"role": "assistant", "content": "First image received."},
        {"role": "user", "content": (
            [_IMAGES[1], {"type": "text", "text": "Compare the images."}]
            if public_images in {"complete", "pending_only"} else "[image: second.png] Compare the images."
        )},
    ]


def _responses_error(*, unsupported=True):
    body = {
        "message": "Unknown parameter: instructions" if unsupported else "Invalid request payload",
        "type": "invalid_request_error",
        "code": "unsupported_parameter" if unsupported else "invalid_payload",
    }
    if unsupported:
        body["param"] = "instructions"
    return BadRequestError(
        body["message"], body=body,
        response=httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1/responses")),
    )


class _ChatStream:
    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield ChatCompletionChunk.model_validate({
            "id": "chatcmpl-fixture", "object": "chat.completion.chunk", "created": 0,
            "model": _MODEL,
            "choices": [{"index": 0, "delta": {"content": "Both images received."}, "finish_reason": "stop"}],
        })

    async def close(self):
        self.closed = True


def _select_chat_route(provider, route):
    if route == "circuit_open":
        for _ in range(_RESPONSES_FAILURE_THRESHOLD):
            provider._record_responses_failure(_MODEL, None)
    elif route == "explicit_chat":
        provider._preset_model_api = ModelAPICapabilities(("chat_completions",), "chat_completions")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("public_images", ["none", "prefix_only", "pending_only"])
async def test_feature_downgrade_keeps_original_error_when_native_images_are_not_portable(
    provider, stream, public_images,
):
    adapter, client = provider
    error = _responses_error()
    client.responses.create.side_effect = error
    context = _context(adapter, recovery=True)
    messages = _messages(public_images)
    before = deepcopy(messages)
    call = adapter.chat_stream_with_retry if stream else adapter.chat_with_retry

    result = await call(messages=messages, model=_MODEL, provider_context=context)

    expected = adapter._handle_error(error)
    assert result.finish_reason == "error"
    assert result.content == expected.content
    assert result.error_status_code == 400
    assert result.error_code == "unsupported_parameter"
    client.responses.create.assert_awaited_once()
    client.chat.completions.create.assert_not_awaited()
    # The attempted Responses request really did include both native images.
    assert image_input_ids(client.responses.create.call_args.kwargs["input"]) == image_input_ids(_IMAGES)
    assert messages == before


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("route", ["circuit_open", "explicit_chat"])
@pytest.mark.parametrize("public_images", ["none", "prefix_only", "pending_only"])
async def test_selected_chat_route_rejects_incomplete_native_image_replay(
    provider, stream, route, public_images,
):
    adapter, client = provider
    _select_chat_route(adapter, route)
    call = adapter.chat_stream_with_context if stream else adapter.chat_with_context

    result = await call(
        messages=_messages(public_images), model=_MODEL, provider_context=_context(adapter),
    )

    assert result.finish_reason == "error"
    assert result.error_kind == "input_unavailable"
    assert result.error_should_retry is False
    assert "Send the images again" in (result.content or "")
    assert "data:image" not in (result.content or "")
    client.responses.create.assert_not_awaited()
    client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("route", ["unsupported_feature", "circuit_open", "explicit_chat"])
async def test_chat_routes_allow_complete_public_image_replay(provider, stream, route):
    adapter, client = provider
    _select_chat_route(adapter, route)
    client.responses.create.side_effect = _responses_error()
    chat_stream = _ChatStream()
    client.chat.completions.create.side_effect = None
    client.chat.completions.create.return_value = chat_stream if stream else {
        "choices": [{"message": {"content": "Both images received."}, "finish_reason": "stop"}],
    }
    messages = _messages("complete")
    before = deepcopy(messages)
    deltas = []

    async def on_content_delta(text):
        deltas.append(text)

    call = adapter.chat_stream_with_retry if stream else adapter.chat_with_retry
    callbacks = {"on_content_delta": on_content_delta} if stream else {}
    result = await call(
        messages=messages, model=_MODEL, provider_context=_context(adapter, recovery=True), **callbacks,
    )

    assert result.finish_reason == "stop"
    assert result.content == "Both images received."
    client.chat.completions.create.assert_awaited_once()
    assert image_input_ids(client.chat.completions.create.call_args.kwargs["messages"]) == image_input_ids(_IMAGES)
    assert "provider_context" not in client.chat.completions.create.call_args.kwargs
    if route == "unsupported_feature":
        client.responses.create.assert_awaited_once()
    else:
        client.responses.create.assert_not_awaited()
    if stream:
        assert deltas == ["Both images received."]
        assert chat_stream.closed
    assert messages == before


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("public_images", ["none", "complete"])
async def test_unknown_responses_400_stays_original_without_chat_downgrade(provider, stream, public_images):
    adapter, client = provider
    error = _responses_error(unsupported=False)
    client.responses.create.side_effect = error
    call = adapter.chat_stream_with_context if stream else adapter.chat_with_context

    result = await call(
        messages=_messages(public_images), model=_MODEL, provider_context=_context(adapter),
    )

    assert result.finish_reason == "error"
    assert result.content == adapter._handle_error(error).content
    assert result.error_status_code == 400
    assert result.error_code == "invalid_payload"
    assert adapter._responses_failures == {}
    client.responses.create.assert_awaited_once()
    client.chat.completions.create.assert_not_awaited()
