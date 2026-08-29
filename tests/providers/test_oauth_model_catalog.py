from __future__ import annotations

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from nanobot.providers.oauth_model_catalog import (
    DEFAULT_XAI_GROK_MODELS_URL,
    OAuthModelCatalog,
    OAuthModelInfo,
    get_oauth_model_catalog,
    invalidate_oauth_model_catalog,
)
from nanobot.providers.xai_oauth import XAIToken


@pytest.fixture(autouse=True)
def _clear_xai_catalog() -> None:
    invalidate_oauth_model_catalog("xai_grok")
    yield
    invalidate_oauth_model_catalog("xai_grok")


def _fallback_model() -> OAuthModelInfo:
    return OAuthModelInfo(id="provider/fallback", label="Fallback")


def test_xai_catalog_fetches_remote_models_and_reuses_capability_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_client = httpx.Client
    captured: dict[str, object] = {}
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "user-42", "email": "user@example.com"}).encode()
    ).decode().rstrip("=")
    token = XAIToken(
        access=f"header.{payload}.signature",
        refresh="refresh-token",
        expires=int(time.time() * 1000) + 3_600_000,
        account_id="user@example.com",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "grok-4.6",
                        "name": "Grok 4.6",
                        "description": "Latest frontier model",
                        "owned_by": "xAI",
                        "context_window": 500_000,
                        "supports_backend_search": True,
                        "reasoning_efforts": [
                            {"value": "xhigh"},
                            {"value": "high"},
                            {"value": "low"},
                        ],
                    },
                    {
                        "id": "grok-next",
                        "_meta": {
                            "name": "Grok Next",
                            "context_window": 750_000,
                            "reasoning_efforts": ["high", "low"],
                        },
                    },
                ]
            },
            request=request,
        )

    def fake_client(**kwargs: object) -> httpx.Client:
        captured["kwargs"] = kwargs
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
            follow_redirects=kwargs["follow_redirects"],
        )

    monkeypatch.setattr(
        "nanobot.providers.oauth_model_catalog._xai_oauth_storage_path",
        lambda: tmp_path / "auth" / "xai.json",
    )
    monkeypatch.setattr(
        "nanobot.providers.oauth_model_catalog._xai_oauth_token",
        lambda _proxy: token,
    )
    monkeypatch.setattr("nanobot.providers.oauth_model_catalog.httpx.Client", fake_client)

    catalog = get_oauth_model_catalog("xai_grok")

    assert catalog.source == "remote"
    assert [model.id for model in catalog.models] == [
        "xai-grok/grok-4.6",
        "xai-grok/grok-next",
    ]
    grok = catalog.find("grok-4.6")
    assert grok is not None
    assert grok.description == "Latest frontier model"
    assert grok.context_window == 500_000
    assert grok.reasoning_efforts == ("xhigh", "high", "low")
    assert grok.supports_backend_search is True
    next_model = catalog.find("xai-grok/grok-next")
    assert next_model is not None
    assert next_model.label == "Grok Next"
    assert next_model.context_window == 750_000
    assert next_model.reasoning_efforts == ("high", "low")

    request = captured["request"]
    assert isinstance(request, httpx.Request)
    assert str(request.url) == DEFAULT_XAI_GROK_MODELS_URL
    assert request.headers["Authorization"] == f"Bearer {token.access}"
    assert request.headers["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert request.headers["x-userid"] == "user-42"
    assert request.headers["x-email"] == "user@example.com"
    assert captured["kwargs"] == {"timeout": 10.0, "follow_redirects": False}
    assert get_oauth_model_catalog("xai_grok").source == "cache"


def test_catalog_single_flights_concurrent_refreshes() -> None:
    calls = 0
    calls_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def fetch(_proxy: str | None) -> tuple[OAuthModelInfo, ...]:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return (OAuthModelInfo(id="provider/remote", label="Remote"),)

    catalog = OAuthModelCatalog(fallback_models=(_fallback_model(),), fetch=fetch)

    def get_catalog(_index: int):
        barrier.wait()
        return catalog.get(cache_key="shared")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(get_catalog, range(8)))

    assert calls == 1
    assert {result.models[0].id for result in results} == {"provider/remote"}
    assert [result.source for result in results].count("remote") == 1
    assert [result.source for result in results].count("cache") == 7


def test_catalog_returns_stale_then_negative_caches_refresh_failure() -> None:
    now = [0.0]
    calls = 0

    def fetch(_proxy: str | None) -> tuple[OAuthModelInfo, ...]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise httpx.ConnectError("offline")
        return (OAuthModelInfo(id="provider/remote", label="Remote"),)

    catalog = OAuthModelCatalog(
        fallback_models=(_fallback_model(),),
        fetch=fetch,
        fresh_ttl_s=10,
        stale_ttl_s=100,
        failure_ttl_s=30,
        monotonic=lambda: now[0],
        wall_clock=lambda: 123.0,
    )

    assert catalog.get(cache_key="one").source == "remote"
    now[0] = 11
    stale = catalog.get(cache_key="one")
    assert stale.source == "stale"
    assert stale.models[0].id == "provider/remote"
    assert catalog.get(cache_key="one").source == "stale"
    assert calls == 2

    now[0] = 101
    fallback = catalog.get(cache_key="one")
    assert fallback.source == "fallback"
    assert fallback.models[0].id == "provider/fallback"
    assert calls == 3


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("offline"),
        ValueError("invalid JSON"),
        httpx.HTTPStatusError(
            "unauthorized",
            request=httpx.Request("GET", DEFAULT_XAI_GROK_MODELS_URL),
            response=httpx.Response(401),
        ),
        httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("GET", DEFAULT_XAI_GROK_MODELS_URL),
            response=httpx.Response(429),
        ),
        httpx.HTTPStatusError(
            "upstream failure",
            request=httpx.Request("GET", DEFAULT_XAI_GROK_MODELS_URL),
            response=httpx.Response(503),
        ),
    ],
)
def test_catalog_falls_back_for_remote_failures(failure: Exception) -> None:
    calls = 0

    def fetch(_proxy: str | None) -> tuple[OAuthModelInfo, ...]:
        nonlocal calls
        calls += 1
        raise failure

    catalog = OAuthModelCatalog(
        fallback_models=(_fallback_model(),),
        fetch=fetch,
        failure_ttl_s=30,
    )

    first = catalog.get(cache_key="one")
    second = catalog.get(cache_key="one")

    assert first.source == "fallback"
    assert second.source == "fallback"
    assert first.models == (_fallback_model(),)
    assert calls == 1


def test_catalog_treats_empty_remote_list_as_failure_and_can_be_invalidated() -> None:
    calls = 0

    def fetch(_proxy: str | None) -> tuple[OAuthModelInfo, ...]:
        nonlocal calls
        calls += 1
        return () if calls == 1 else (OAuthModelInfo(id="provider/new", label="New"),)

    catalog = OAuthModelCatalog(
        fallback_models=(_fallback_model(),),
        fetch=fetch,
        failure_ttl_s=30,
    )

    assert catalog.get(cache_key="one").source == "fallback"
    catalog.invalidate()
    refreshed = catalog.get(cache_key="one")
    assert refreshed.source == "remote"
    assert refreshed.models[0].id == "provider/new"
    assert calls == 2
