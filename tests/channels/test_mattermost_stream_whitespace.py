"""Mattermost streams must preserve whitespace between content deltas."""

import json

import httpx
import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.mattermost.runtime import MattermostChannel


@pytest.mark.parametrize("separator", [" ", "\n", "\t"])
async def test_stream_preserves_whitespace_only_delta(separator):
    channel = MattermostChannel({"serverUrl": "https://mattermost.example"}, MessageBus())
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "post-example"})

    async with httpx.AsyncClient(
        base_url="https://mattermost.example", transport=httpx.MockTransport(respond)
    ) as client:
        channel._http_client = client
        await channel.send_delta("chat", "Hello", stream_id="stream")
        await channel.send_delta("chat", separator, stream_id="stream")
        await channel.send_delta("chat", "world", stream_id="stream")
        await channel.send_delta("chat", "", stream_id="stream", stream_end=True)

    assert len(requests) == 1
    assert json.loads(requests[0].content) == {
        "channel_id": "chat", "message": f"Hello{separator}world",
    }
