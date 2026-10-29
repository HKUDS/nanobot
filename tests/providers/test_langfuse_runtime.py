"""Startup/reload and best-effort contracts at the provider edge."""

import sys
from importlib.machinery import ModuleSpec
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.observability import langfuse
from nanobot.observability.config import LangfuseConfig
from nanobot.providers.base import LLMResponse
from nanobot.providers.factory import build_provider_snapshot, load_provider_snapshot, make_provider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider


@pytest.fixture(autouse=True)
def isolated_startup(monkeypatch):
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_TRACING_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    with langfuse.langfuse_runtime_owner():
        yield


def _config(*, enabled=True):
    return Config.model_validate({
        "agents": {"defaults": {"provider": "openai_codex", "model": "primary"}},
        "observability": {"langfuse": {
            "enabled": enabled, "publicKey": "startup-public", "secretKey": "startup-secret",
            "baseUrl": "https://startup.example",
        }},
    })


@pytest.fixture
def traces(monkeypatch):
    events = []
    constructors = []

    def create_client(**kwargs):
        settings = LangfuseConfig(**{key: value for key, value in kwargs.items() if key != "tracing_enabled"})
        constructors.append(settings.model_copy(deep=True))

        def start_observation(**kwargs):
            events.append((settings.secret_key, kwargs))
            return SimpleNamespace(update=lambda **_: None, end=lambda: None)

        return SimpleNamespace(start_observation=start_observation, shutdown=Mock())

    monkeypatch.setattr("importlib.util.find_spec", lambda name: ModuleSpec(name, loader=None))
    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=create_client))
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda **_: SimpleNamespace(account_id="acct", access="token"),
    )
    return constructors, events


async def test_startup_survives_save_reload_new_session_and_lazy_fallback(monkeypatch, traces, tmp_path):
    constructors, events = traces
    config = _config()
    config.agents.defaults.fallback_models = ["backup"]
    config.model_presets["backup"] = config.resolve_default_preset().model_copy(update={"model": "backup"})
    runtime = langfuse.initialize_langfuse(config)
    before_save = build_provider_snapshot(config)
    path = tmp_path / "config.json"
    config.observability.langfuse = LangfuseConfig(enabled=False)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "changed-env-secret")
    save_config(config, path)
    reloaded = load_provider_snapshot(path)
    new_session = make_provider(config, preset_name="backup")

    async def request(url, headers, body, **kwargs):
        if body["model"] == "primary":
            return LLMResponse(content="server unavailable", finish_reason="error", error_status_code=503)
        return LLMResponse(content="backup answer")

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", request)
    try:
        for provider in (before_save.provider, reloaded.provider, new_session):
            result = await provider.chat([{"role": "user", "content": "hello"}])
            assert result.content == "backup answer"
    finally:
        for provider in (before_save.provider, reloaded.provider, new_session):
            await provider.aclose()
    assert len(constructors) == 1
    assert events and {secret for secret, _ in events} == {"startup-secret"}
    assert langfuse.initialize_langfuse(config) is runtime
    active = langfuse.get_running_langfuse_config()
    assert active is not None and active.enabled
    active.secret_key = "caller mutation"
    assert runtime.settings.secret_key == "startup-secret"


async def test_unconfigured_boot_freezes_disable_before_first_provider(monkeypatch, traces):
    constructors, events = traces
    config = Config()
    config.observability.langfuse = LangfuseConfig(enabled=False)
    langfuse.initialize_langfuse(config)  # No provider exists at startup.
    configured = _config(enabled=True)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "new-env-secret")
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex",
        AsyncMock(return_value=LLMResponse(content="works")),
    )
    provider = make_provider(configured)
    try:
        assert (await provider.chat([{"role": "user", "content": "hello"}])).content == "works"
    finally:
        await provider.aclose()
    assert constructors == []
    assert events == []
    assert langfuse.get_running_langfuse_active() is False


async def test_install_after_startup_waits_for_restart(monkeypatch, traces):
    constructors, events = traces
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    config = _config()
    langfuse.initialize_langfuse(config)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: ModuleSpec(name, loader=None))
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex",
        AsyncMock(return_value=LLMResponse(content="works")),
    )
    provider = make_provider(config)
    try:
        assert (await provider.chat([{"role": "user", "content": "hello"}])).content == "works"
    finally:
        await provider.aclose()
    assert langfuse.get_running_langfuse_available() is False
    assert constructors == [] and events == []


async def test_sdk_initialization_failure_keeps_chat_available(monkeypatch, traces):
    def broken_client(**kwargs):
        raise RuntimeError("unsafe upstream error with credentials")

    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=broken_client))
    langfuse.initialize_langfuse(_config())
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider._request_codex",
        AsyncMock(return_value=LLMResponse(content="works")),
    )
    provider = OpenAICodexProvider()
    try:
        assert (await provider.chat([{"role": "user", "content": "hello"}])).content == "works"
    finally:
        await provider.aclose()
    assert langfuse.get_running_langfuse_available() is True
    assert langfuse.get_running_langfuse_active() is False


@pytest.mark.parametrize("failed_start", [False, True])
def test_independent_runtime_owners_close_and_refresh_startup_state(monkeypatch, traces, failed_start):
    constructors, _ = traces
    first = None
    first_client = None
    try:
        with langfuse.langfuse_runtime_owner():
            first = langfuse.initialize_langfuse(_config())
            first_client = first._client
            assert first.active and first.available
            if failed_start:
                raise RuntimeError("startup failed")
    except RuntimeError as exc:
        assert failed_start and str(exc) == "startup failed"
    assert first is not None and not first.active
    assert first_client is not None
    first_client.shutdown.assert_called_once()
    assert langfuse.get_running_langfuse_config() is None
    assert langfuse.get_running_langfuse_available() is None
    assert langfuse.get_running_langfuse_active() is None

    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    second_config = _config(enabled=False)
    with langfuse.langfuse_runtime_owner():
        second = langfuse.initialize_langfuse(second_config)
        assert second is not first
        assert not second.settings.enabled
        assert second.available is False
        assert langfuse.get_running_langfuse_config() == second_config.observability.langfuse
    assert len(constructors) == 1
