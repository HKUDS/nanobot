"""Regression tests for concurrent token refresh in GitHubCopilotProvider (#4677)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.providers import github_copilot_provider as gc


@pytest.mark.asyncio
async def test_concurrent_token_refresh_fetches_once(monkeypatch):
    """A competing caller waits for the in-flight exchange and reuses its token."""
    monkeypatch.setattr(gc, "_load_github_token", lambda: SimpleNamespace(access="github-token"))

    fetch_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()
    competing_started = asyncio.Event()

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"token": "copilot-token", "refresh_in": 1500}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *, headers):
            nonlocal fetch_count
            fetch_count += 1
            entered.set()
            await release.wait()
            return FakeResponse()

    monkeypatch.setattr(gc.httpx, "AsyncClient", FakeAsyncClient)
    provider = gc.GitHubCopilotProvider()

    async def competing_call():
        # No suspension between this signal and entering the token path.
        competing_started.set()
        return await provider._get_copilot_access_token()

    task_a = asyncio.create_task(provider._get_copilot_access_token())
    tasks = [task_a]
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        task_b = asyncio.create_task(competing_call())
        tasks.append(task_b)
        await asyncio.wait_for(competing_started.wait(), timeout=5)
        assert not task_a.done()
        assert not task_b.done()
        assert fetch_count == 1

        release.set()
        tokens = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
        assert tokens == ["copilot-token", "copilot-token"]
        assert fetch_count == 1
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await provider.aclose()
