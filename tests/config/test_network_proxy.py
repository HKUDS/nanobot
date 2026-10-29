"""One shared address with explicit feature opt-in."""

import json

import httpx
import pytest

from nanobot.config.loader import load_config, resolve_config_env_vars, save_config
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import Config


def test_shared_proxy_choices_survive_save_and_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_PROVIDERS", json.dumps({
        "openai": {"useProxy": True}, "openaiCodex": {"useProxy": True}, "xaiGrok": {"useProxy": True},
    }))
    path = tmp_path / "config.json"
    original = {
        "network": {"proxy": "socks5://localhost:1080"},
        "tools": {"web": {"useProxy": False}},
        "channels": {"telegram": {"useProxy": True}},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    config = load_config(path)
    assert config.providers.openai.use_proxy is True
    assert config.providers.openai_codex.use_proxy is True
    assert config.providers.xai_grok.use_proxy is True
    config.providers.openai.use_proxy = False
    config.providers.openai_codex.use_proxy = False
    config.providers.xai_grok.use_proxy = False
    config.tools.web.use_proxy = True
    config.channels.telegram["useProxy"] = False
    save_config(config, path)

    reloaded = load_config(path)
    assert reloaded.network.proxy == "socks5://localhost:1080"
    assert reloaded.providers.openai.use_proxy is False
    assert reloaded.providers.openai_codex.use_proxy is False
    assert reloaded.providers.xai_grok.use_proxy is False
    assert reloaded.tools.web.use_proxy is True
    assert reloaded.channels.telegram["useProxy"] is False


def test_proxy_opt_in_does_not_fall_back_when_unconfigured():
    network = NetworkConfig()
    assert network.resolve_proxy(False) is None
    with pytest.raises(ValueError, match="Advanced"):
        network.resolve_proxy(True)


def test_shared_proxy_environment_reference_stays_unresolved_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_PROXY", "http://localhost:7890")
    config = Config(network=NetworkConfig(proxy="${SHARED_PROXY}"))
    config.tools.web.use_proxy = True
    resolved = resolve_config_env_vars(config)
    assert resolved.network.resolve_proxy(True) == "http://localhost:7890"
    assert config.network.proxy == "${SHARED_PROXY}"
    path = tmp_path / "config.json"
    save_config(config, path)
    assert load_config(path).network.proxy == "${SHARED_PROXY}"


@pytest.mark.parametrize("address", ["file:///tmp/proxy", "http://host:99999", "http://host/path", "http://user:secret@["])
def test_invalid_shared_proxy_has_a_safe_error(address):
    with pytest.raises(ValueError, match="proxy URL") as caught:
        NetworkConfig.normalize_proxy(address)
    assert address not in str(caught.value)


@pytest.mark.parametrize("address", ["http://proxy.example:8080", "${PROXY_SCHEME}://${PROXY_HOST}:8080"])
@pytest.mark.parametrize(
    "userinfo, environment, expected_auth",
    [
        ("${PROXY_AUTH}", {"PROXY_AUTH": "alice:pw"}, (b"alice", b"pw")),
        ("${PROXY_AUTH}", {"PROXY_AUTH": "alice%40mail:p%2Fa%23b%3Fc%40d%3Ae%2525f"}, (b"alice@mail", b"p/a#b?c@d:e%25f")),
        ("${PROXY_AUTH}", {"PROXY_AUTH": "alice:p/a#b?c@d:e%f"}, (b"alice", b"p/a#b?c@d:e%f")),
        (
            "${PROXY_USER}:${PROXY_PASSWORD}",
            {"PROXY_USER": "alice/a#b?c@d:e%25f", "PROXY_PASSWORD": "p/a#b?c@d:e%25f"},
            (b"alice/a#b?c@d:e%25f", b"p/a#b?c@d:e%25f"),
        ),
    ],
    ids=["combined-auth", "combined-encoded-auth", "combined-special-password", "credential-components"],
)
def test_proxy_userinfo_references_round_trip_with_httpx_auth(tmp_path, monkeypatch, address, userinfo, environment, expected_auth):
    monkeypatch.setenv("PROXY_SCHEME", "http")
    monkeypatch.setenv("PROXY_HOST", "proxy.example")
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    scheme, host = address.split("://", 1)
    template = f"{scheme}://{userinfo}@{host}"
    original = {
        "network": {"proxy": template}, "providers": {"openai": {"useProxy": True}},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(original), encoding="utf-8")

    config = load_config(path)
    assert config.network.proxy == template
    assert config.providers.openai.use_proxy is True
    for current in (config, resolve_config_env_vars(config)):
        proxy = httpx.Proxy(current.network.resolve_proxy(current.providers.openai.use_proxy))
        assert proxy.url.host == "proxy.example"
        assert proxy.url.port == 8080
        assert proxy.raw_auth == expected_auth
    assert json.loads(path.read_text(encoding="utf-8")) == original
    save_config(config, path)

    saved_text = path.read_text(encoding="utf-8")
    assert json.loads(saved_text)["network"]["proxy"] == template
    for value in environment.values():
        assert value not in saved_text
    reloaded = load_config(path)
    assert reloaded.network.proxy == template
    assert httpx.Proxy(resolve_config_env_vars(reloaded).network.resolve_proxy(True)).raw_auth == expected_auth
