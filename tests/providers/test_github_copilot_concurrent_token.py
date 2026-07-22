"""Regression tests for concurrent token refresh in GitHubCopilotProvider (#4677)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.providers import github_copilot_provider as gc


@pytest.mark.asyncio
async def test_concurrent_token_refresh_fetches_once(monkeypatch):
    """Two concurrent _get_copilot_access_token calls should trigger only one
    HTTP fetch when the token is expired, not two."""
    monkeypatch.setattr(gc, "_load_github_token", lambda: SimpleNamespace(access="github-token"))

    fetch_count = 0

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
            # Simulate network latency so both coroutines overlap before the
            # lock serializes them.
            await asyncio.sleep(0.05)
            return FakeResponse()

    monkeypatch.setattr(gc.httpx, "AsyncClient", FakeAsyncClient)

    provider = gc.GitHubCopilotProvider()
    # Force token expiry.
    provider._copilot_access_token = None
    provider._copilot_expires_at = 0.0

    token_a, token_b = await asyncio.gather(
        provider._get_copilot_access_token(),
        provider._get_copilot_access_token(),
    )

    assert token_a == "copilot-token"
    assert token_b == "copilot-token"
    assert fetch_count == 1, (
        f"Expected exactly 1 token fetch under concurrency, got {fetch_count}"
    )


@pytest.mark.asyncio
async def test_second_call_returns_cached_token_while_first_in_flight(monkeypatch):
    """If task A is mid-fetch inside the lock, task B should wait, then find
    the cached token and skip the HTTP call entirely."""
    monkeypatch.setattr(gc, "_load_github_token", lambda: SimpleNamespace(access="github-token"))

    fetch_count = 0

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"token": "cached-token", "refresh_in": 1500}

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
            await asyncio.sleep(0.1)
            return FakeResponse()

    monkeypatch.setattr(gc.httpx, "AsyncClient", FakeAsyncClient)

    provider = gc.GitHubCopilotProvider()
    provider._copilot_access_token = None
    provider._copilot_expires_at = 0.0

    # Start task A, let it acquire the lock and begin the HTTP fetch.
    task_a = asyncio.create_task(provider._get_copilot_access_token())
    await asyncio.sleep(0.02)  # task A is now inside the lock, mid-fetch

    # Task B starts while A is still in flight.
    token_b = await provider._get_copilot_access_token()
    token_a = await task_a

    assert token_a == "cached-token"
    assert token_b == "cached-token"
    assert fetch_count == 1


@pytest.mark.asyncio
async def test_copilot_token_lock_exists():
    """Provider should have an asyncio.Lock for token refresh."""
    provider = gc.GitHubCopilotProvider()
    assert isinstance(provider._copilot_token_lock, asyncio.Lock)
