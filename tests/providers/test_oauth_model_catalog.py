from __future__ import annotations

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from nanobot.providers.oauth_model_catalog import (
    OAuthModelCatalog,
    get_oauth_model_catalog,
    invalidate_oauth_model_catalog,
)
from nanobot.providers.openai_codex_provider import (
    DEFAULT_OPENAI_CODEX_MODELS_URL,
    OPENAI_CODEX_CATALOG_CLIENT_VERSION,
)
from nanobot.providers.registry import ProviderModelSpec
from nanobot.providers.xai_grok_provider import DEFAULT_XAI_GROK_MODELS_URL
from nanobot.providers.xai_oauth import XAIToken


@pytest.fixture(autouse=True)
def _clear_oauth_catalogs() -> None:
    for provider in ("openai_codex", "xai_grok", "github_copilot"):
        invalidate_oauth_model_catalog(provider)
    yield
    for provider in ("openai_codex", "xai_grok", "github_copilot"):
        invalidate_oauth_model_catalog(provider)


def _fallback_model() -> ProviderModelSpec:
    return ProviderModelSpec(id="provider/fallback", label="Fallback")


def test_xai_catalog_fetches_remote_models_and_reuses_capability_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_client = httpx.Client
    captured: dict[str, object] = {}
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": "user-42", "email": "user@example.com"}).encode()
        )
        .decode()
        .rstrip("=")
    )
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
        "nanobot.providers.xai_grok_provider.get_xai_oauth_storage_path",
        lambda: tmp_path / "auth" / "xai.json",
    )
    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_oauth_login_status",
        lambda: token,
    )
    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_oauth_token",
        lambda **_kwargs: token,
    )
    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.Client", fake_client)

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


def test_openai_codex_catalog_uses_account_catalog_and_filters_hidden_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_client = httpx.Client
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "slug": "gpt-new",
                        "display_name": "GPT New",
                        "description": "New model",
                        "context_window": 300_000,
                        "priority": 2,
                        "visibility": "list",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "high"},
                        ],
                    },
                    {
                        "slug": "gpt-first",
                        "display_name": "GPT First",
                        "priority": 1,
                    },
                    {
                        "slug": "internal-model",
                        "display_name": "Internal",
                        "visibility": "hide",
                        "priority": 0,
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

    class Storage:
        def load(self) -> SimpleNamespace:
            return SimpleNamespace(access="secret", account_id="account-42")

        def get_token_path(self) -> Path:
            return tmp_path / "auth" / "openai-codex.json"

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.FileTokenStorage",
        lambda **_kwargs: Storage(),
    )
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda **_kwargs: SimpleNamespace(access="secret", account_id="account-42"),
    )
    monkeypatch.setattr("nanobot.providers.openai_codex_provider.httpx.Client", fake_client)

    catalog = get_oauth_model_catalog("openai_codex")

    assert catalog.source == "remote"
    assert [model.id for model in catalog.models] == [
        "openai-codex/gpt-first",
        "openai-codex/gpt-new",
    ]
    assert catalog.models[1].context_window == 300_000
    assert catalog.models[1].reasoning_efforts == ("low", "high")
    request = captured["request"]
    assert isinstance(request, httpx.Request)
    assert request.url.copy_with(query=None) == httpx.URL(DEFAULT_OPENAI_CODEX_MODELS_URL)
    assert request.url.params["client_version"] == OPENAI_CODEX_CATALOG_CLIENT_VERSION
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.headers["chatgpt-account-id"] == "account-42"


def test_github_copilot_catalog_only_lists_compatible_chat_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_client = httpx.Client
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/copilot_internal/v2/token"):
            return httpx.Response(
                200,
                json={
                    "token": "copilot-secret",
                    "endpoints": {"api": "https://api.individual.githubcopilot.com"},
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "claude-sonnet",
                        "name": "Claude Sonnet",
                        "model_picker_enabled": True,
                        "policy": {"state": "enabled"},
                        "supported_endpoints": ["/chat/completions"],
                        "capabilities": {
                            "supports": {"reasoning_effort": ["low", "high"]},
                            "limits": {"max_context_window_tokens": 200_000},
                        },
                    },
                    {
                        "id": "gpt-5.4-mini",
                        "name": "GPT-5.4 Mini",
                        "model_picker_enabled": True,
                        "supported_endpoints": ["/responses"],
                    },
                    {
                        "id": "unknown-responses-only",
                        "name": "Unknown Responses only",
                        "model_picker_enabled": True,
                        "supported_endpoints": ["/responses"],
                    },
                    {
                        "id": "disabled",
                        "model_picker_enabled": True,
                        "policy": {"state": "disabled"},
                        "supported_endpoints": ["/chat/completions"],
                    },
                ]
            },
            request=request,
        )

    def fake_client(**kwargs: object) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
            follow_redirects=kwargs["follow_redirects"],
        )

    class Storage:
        def load(self) -> SimpleNamespace:
            return SimpleNamespace(access="github-secret", account_id="octocat")

        def get_token_path(self) -> Path:
            return tmp_path / "auth" / "github-copilot.json"

    monkeypatch.setattr(
        "nanobot.providers.github_copilot_provider.get_storage",
        lambda: Storage(),
    )
    monkeypatch.setattr("nanobot.providers.github_copilot_provider.httpx.Client", fake_client)

    catalog = get_oauth_model_catalog("github_copilot")

    assert catalog.source == "remote"
    assert [model.id for model in catalog.models] == [
        "github-copilot/claude-sonnet",
        "github-copilot/gpt-5.4-mini",
    ]
    assert catalog.models[0].context_window == 200_000
    assert catalog.models[0].reasoning_efforts == ("low", "high")
    assert len(captured) == 2
    assert captured[0].headers["Authorization"] == "token github-secret"
    assert captured[1].headers["Authorization"] == "Bearer copilot-secret"
    assert str(captured[1].url) == "https://api.individual.githubcopilot.com/models"
    assert get_oauth_model_catalog("github_copilot").source == "cache"
    assert get_oauth_model_catalog(
        "github_copilot",
        proxy="http://proxy.example:8080",
    ).source == "remote"
    assert len(captured) == 4


def test_catalog_single_flights_concurrent_refreshes() -> None:
    calls = 0
    calls_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def fetch(_proxy: str | None) -> tuple[ProviderModelSpec, ...]:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return (ProviderModelSpec(id="provider/remote", label="Remote"),)

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


def test_catalog_invalidation_discards_an_inflight_account_refresh() -> None:
    started = threading.Event()
    release = threading.Event()
    identity = ["old-account"]

    def fetch(_proxy: str | None) -> tuple[ProviderModelSpec, ...]:
        current = identity[0]
        if current == "old-account":
            started.set()
            assert release.wait(timeout=2)
        return (ProviderModelSpec(id=f"provider/{current}", label=current),)

    catalog = OAuthModelCatalog(fallback_models=(_fallback_model(),), fetch=fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_future = pool.submit(catalog.get, cache_key="old-key")
        assert started.wait(timeout=2)
        identity[0] = "new-account"
        catalog.invalidate()
        new_future = pool.submit(catalog.get, cache_key="new-key")
        new_result = new_future.result(timeout=2)
        release.set()
        old_result = old_future.result(timeout=2)

    assert old_result.source == "fallback"
    assert new_result.models[0].id == "provider/new-account"

    identity[0] = "old-account"
    assert catalog.get(cache_key="old-key").models[0].id == "provider/old-account"


def test_catalog_bounds_failure_only_keys() -> None:
    calls = 0

    def fetch(_proxy: str | None) -> tuple[ProviderModelSpec, ...]:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline")

    catalog = OAuthModelCatalog(
        fallback_models=(_fallback_model(),),
        fetch=fetch,
        max_entries=2,
    )

    for key in ("one", "two", "three"):
        assert catalog.get(cache_key=key).source == "fallback"

    assert calls == 3
    assert catalog.get(cache_key="one").source == "fallback"
    assert calls == 4


def test_catalog_returns_stale_then_negative_caches_refresh_failure() -> None:
    now = [0.0]
    calls = 0

    def fetch(_proxy: str | None) -> tuple[ProviderModelSpec, ...]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise httpx.ConnectError("offline")
        return (ProviderModelSpec(id="provider/remote", label="Remote"),)

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

    def fetch(_proxy: str | None) -> tuple[ProviderModelSpec, ...]:
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

    def fetch(_proxy: str | None) -> tuple[ProviderModelSpec, ...]:
        nonlocal calls
        calls += 1
        return () if calls == 1 else (ProviderModelSpec(id="provider/new", label="New"),)

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
