import httpx
import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.observability.config import LangfuseConfig
from nanobot.security.network import PinnedDNSAsyncTransport
from nanobot.webui import settings_observability as observability
from nanobot.webui.settings_contracts import WebUISettingsError


@pytest.fixture(autouse=True)
def isolate_langfuse_environment(monkeypatch):
    for name in ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HOST", "LANGFUSE_TRACING_ENABLED"):
        monkeypatch.delenv(name, raising=False)


def test_first_settings_save_preserves_environment_references(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-env-project")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-env-secret")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")
    monkeypatch.setattr(observability, "langfuse_installed", lambda: True)
    config = Config()
    payload = observability.observability_settings_payload(config)
    assert payload["source"] == "environment"
    assert payload["configured"] is True
    update = observability.parse_observability_update({
        "enabled": True, "base_url": payload["base_url"],
    })
    assert observability.update_observability_settings(config, update)
    path = tmp_path / "config.json"
    save_config(config, path)
    saved = load_config(path).observability.langfuse
    assert saved.public_key == "${LANGFUSE_PUBLIC_KEY}"
    assert saved.secret_key == "${LANGFUSE_SECRET_KEY}"
    assert saved.base_url == "${LANGFUSE_BASE_URL}"
    assert "sk-env-secret" not in path.read_text(encoding="utf-8")
    assert observability.observability_settings_payload(config)["uses_environment"] is True


def test_explicit_missing_key_is_not_filled_from_environment(monkeypatch):
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-unrelated-project")
    config = Config()
    config.observability.langfuse = LangfuseConfig(public_key="pk-explicit")
    with pytest.raises(WebUISettingsError, match="langfuse_missing_credentials"):
        observability.update_observability_settings(config, observability.parse_observability_update({
            "enabled": True, "base_url": "https://langfuse.example",
        }))
    assert config.observability.langfuse.enabled is False
    assert config.observability.langfuse.secret_key == ""


def test_enable_requires_support_but_disabled_draft_can_be_saved(monkeypatch):
    monkeypatch.setattr(observability, "langfuse_installed", lambda: False)
    config = Config()
    values = {
        "enabled": True, "base_url": "https://langfuse.example",
        "public_key": "pk-project", "secret_key": "sk-project",
    }
    with pytest.raises(WebUISettingsError, match="langfuse_support_required"):
        observability.update_observability_settings(config, observability.parse_observability_update(values))
    assert config.observability.langfuse is None
    values["enabled"] = False
    assert observability.update_observability_settings(config, observability.parse_observability_update(values))
    assert config.observability.langfuse.secret_key == "sk-project"


def test_invalid_settings_diagnostics_do_not_echo_credentials():
    with pytest.raises(WebUISettingsError) as failure:
        observability.parse_observability_update({
            "enabled": True, "base_url": "https://langfuse.example", "secret_key": ["sk-private-value"],
        })
    assert str(failure.value) == "Invalid Langfuse settings"


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_probe_respects_private_service_allowlist(monkeypatch, allowed):
    import ipaddress

    monkeypatch.setattr("nanobot.security.network._allowed_networks", [ipaddress.ip_network("127.0.0.1/32")] if allowed else [])
    monkeypatch.setattr(observability, "httpx_env_proxy_mounts", lambda: {})
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "project"}]})

    monkeypatch.setattr(observability, "PinnedDNSAsyncTransport", lambda: PinnedDNSAsyncTransport(
        inner=httpx.MockTransport(respond),
    ))
    result = await observability.probe_langfuse_connection(Config(), observability.parse_observability_update({
        "enabled": False, "base_url": "http://127.0.0.1:3000", "public_key": "pk-project", "secret_key": "sk-project",
    }))
    assert result == ({"ok": True} if allowed else {"ok": False, "error": "blocked_url"})
    assert len(requests) == int(allowed)


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body", "expected"), [
    (401, {}, "invalid_credentials"),
    (302, {}, "unreachable"),
    (200, {"message": "not a Langfuse API"}, "unreachable"),
])
async def test_probe_reports_authentication_errors_and_does_not_follow_redirects(monkeypatch, status, body, expected):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Location": "http://127.0.0.1/private"})

    monkeypatch.setattr(observability, "validate_url_target", lambda _url: (True, ""))
    monkeypatch.setattr(observability, "httpx_env_proxy_mounts", lambda: {})
    monkeypatch.setattr(observability, "PinnedDNSAsyncTransport", lambda: httpx.MockTransport(respond))
    result = await observability.probe_langfuse_connection(Config(), observability.parse_observability_update({
        "enabled": False, "base_url": "https://langfuse.example", "public_key": "pk-project", "secret_key": "sk-project",
    }))
    assert result == {"ok": False, "error": expected}
    assert len(requests) == 1


def test_install_support_preserves_disabled_configuration_and_install_policy(tmp_path, monkeypatch):
    from nanobot.optional_features import InstallResult, OptionalFeatureError
    from nanobot.webui.nanobot_features_api import nanobot_features_action

    config_path = tmp_path / "config.json"
    config = Config()
    config.observability.langfuse = LangfuseConfig(enabled=False, secret_key="stored-secret")
    save_config(config, config_path)
    before = config_path.read_bytes()
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {"langfuse": ["langfuse>=4.7.0,<5"]})
    installed = False

    def install(_name, dependencies, *, runner):
        nonlocal installed
        installed = True
        return InstallResult(True, "langfuse support", ["pip", *dependencies])

    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda *_: installed)
    monkeypatch.setattr("nanobot.optional_features.install_extra", install)
    query = {"name": ["langfuse"], "install_only": ["true"]}
    with pytest.raises(OptionalFeatureError):
        nanobot_features_action("enable", query, allow_install=False, config_path=config_path)
    assert not installed
    result = nanobot_features_action("enable", query, config_path=config_path)
    assert result["features"][0]["installed"] is True
    assert result["requires_restart"] is True
    assert config_path.read_bytes() == before


def test_disabled_save_rejects_unresolved_references_that_would_break_restart(monkeypatch):
    monkeypatch.delenv("UNSET_TRACE_SECRET", raising=False)
    config = Config()
    update = observability.parse_observability_update({
        "enabled": False, "base_url": "https://langfuse.example", "secret_key": "${UNSET_TRACE_SECRET}",
    })
    with pytest.raises(WebUISettingsError, match="langfuse_missing_credentials"):
        observability.update_observability_settings(config, update)
    assert config.observability.langfuse is None
