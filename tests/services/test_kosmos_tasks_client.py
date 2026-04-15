from __future__ import annotations

import asyncio
from unittest.mock import patch

from nanobot.services.kosmos_tasks import KosmosTasksClient


def test_unwrap_list_accepts_legacy_list() -> None:
    data = [{"id": "t1"}, {"id": "t2"}]
    out = KosmosTasksClient._unwrap_list(data, "tasks")
    assert out == data


def test_unwrap_list_accepts_kosmos_envelope() -> None:
    data = {"tasks": [{"id": "t1"}], "total": 1}
    out = KosmosTasksClient._unwrap_list(data, "tasks")
    assert out == [{"id": "t1"}]


def test_unwrap_list_handles_invalid_payload() -> None:
    out = KosmosTasksClient._unwrap_list({"tasks": "bad"}, "tasks")
    assert out == []


def test_publish_activity_returns_true_on_accepted() -> None:
    async def _run() -> None:
        client = KosmosTasksClient(base_url="http://example.test")

        class _Resp:
            def __init__(self, status: int):
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Session:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def post(self, url: str, json: dict):
                assert url == "http://example.test/api/events/activity"
                assert json == {"type": "status", "message": "ok"}
                return _Resp(202)

        with patch("nanobot.services.nanocats_tasks.aiohttp.ClientSession", _Session):
            ok = await client.publish_activity({"type": "status", "message": "ok"})
            assert ok is True

    asyncio.run(_run())
