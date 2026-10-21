"""One shared address, explicit feature opt-in, and legacy config migration."""

import json

import pytest

from nanobot.config.loader import ConfigLoadError, load_config, resolve_config_env_vars, save_config
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import Config


@pytest.mark.parametrize("address", ["http://127.0.0.1:7890", "socks5://user:pass@localhost:1080", "${SHARED_PROXY}"])
def test_legacy_proxy_migrates_once_across_features(tmp_path, address):
    path = tmp_path / "config.json"
    original = {
        "providers": {"openai": {"proxy": address}, "openaiCodex": {"proxy": address}},
        "tools": {"web": {"proxy": address}},
        "channels": {"telegram": {"proxy": address}, "slack": {"proxy": ""}},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    config = load_config(path)
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert config.network.proxy == address
    assert config.providers.openai.use_proxy is True
    assert config.providers.openai_codex.use_proxy is True
    assert config.tools.web.use_proxy is True
    assert config.channels.telegram["useProxy"] is True
    assert "useProxy" not in config.channels.slack
    config.providers.openai.use_proxy = False
    save_config(config, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["network"]["proxy"] == address
    assert "proxy" not in saved["providers"]["openai"]
    assert "proxy" not in saved["tools"]["web"]
    assert "proxy" not in saved["channels"]["telegram"]
    assert load_config(path).providers.openai.use_proxy is False


def test_multiple_legacy_addresses_require_one_explicit_global_address(tmp_path):
    path = tmp_path / "config.json"
    original = {"tools": {"web": {"proxy": "http://secret:password@localhost:7890"}}, "channels": {"discord": {"proxy": "http://localhost:7891"}}}
    path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ConfigLoadError, match="Multiple legacy proxy addresses") as caught:
        load_config(path)
    assert "secret" not in str(caught.value)
    assert json.loads(path.read_text(encoding="utf-8")) == original
    original["network"] = {"proxy": "http://localhost:7892"}
    path.write_text(json.dumps(original), encoding="utf-8")
    config = load_config(path)
    assert config.network.proxy == "http://localhost:7892"
    assert config.tools.web.use_proxy is True
    assert config.channels.discord["useProxy"] is True


def test_discord_proxy_credentials_move_into_the_shared_url(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"channels": {"discord": {"proxy": "localhost:7890", "proxyUsername": "user@host", "proxyPassword": "pass:word"}}}), encoding="utf-8")
    config = load_config(path)
    assert config.network.proxy == "http://user%40host:pass%3Aword@localhost:7890"
    assert config.channels.discord == {"useProxy": True}


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


@pytest.mark.parametrize("file_present", [False, True])
def test_environment_legacy_proxy_migrates_after_source_merge(tmp_path, monkeypatch, file_present):
    proxy = "http://localhost:7890"
    monkeypatch.setenv("NANOBOT_PROVIDERS", json.dumps({"openai": {"proxy": proxy}}))
    monkeypatch.setenv("NANOBOT_TOOLS", json.dumps({"web": {"proxy": proxy}}))
    monkeypatch.setenv("NANOBOT_CHANNELS", json.dumps({"telegram": {"proxy": proxy}}))
    path = tmp_path / "config.json"
    if file_present:
        path.write_text(json.dumps({"providers": {"openai": {"apiKey": "test-key"}}}), encoding="utf-8")
    config = load_config(path)
    assert config.network.proxy == proxy
    assert config.providers.openai.use_proxy is True
    assert config.tools.web.use_proxy is True
    assert config.channels.telegram == {"useProxy": True}
    save_config(config, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["network"]["proxy"] == proxy
    assert "proxy" not in saved["providers"]["openai"]
    config.providers.openai.use_proxy = False
    save_config(config, path)
    assert load_config(path).providers.openai.use_proxy is False


def test_file_proxy_and_opt_out_take_precedence_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_PROVIDERS", json.dumps({"openai": {"proxy": "http://environment:7890"}}))
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"providers": {"openai": {"proxy": "http://file:7891", "useProxy": False}}}), encoding="utf-8")
    config = load_config(path)
    assert config.network.proxy == "http://file:7891"
    assert config.providers.openai.use_proxy is False


@pytest.mark.parametrize("password", ["a/b", "a#b?c", "a@b:c%"])
def test_discord_credential_references_are_escaped_without_persisting_secrets(tmp_path, monkeypatch, password):
    from urllib.parse import unquote, urlsplit

    monkeypatch.setenv("PROXY_USER", "alice@example")
    monkeypatch.setenv("PROXY_PASSWORD", password)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"channels": {"discord": {"proxy": "http://localhost:7890", "proxyUsername": "${PROXY_USER}", "proxyPassword": "${PROXY_PASSWORD}"}}}), encoding="utf-8")
    config = load_config(path)
    for network in (config.network, resolve_config_env_vars(config).network):
        proxy = network.resolve_proxy(True)
        parsed = urlsplit(proxy)
        assert parsed.hostname == "localhost"
        assert parsed.port == 7890
        assert unquote(parsed.username) == "alice@example"
        assert unquote(parsed.password) == password
    save_config(config, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["network"]["proxy"] == "http://${PROXY_USER}:${PROXY_PASSWORD}@localhost:7890"
    assert "alice@example" not in path.read_text(encoding="utf-8")
    assert load_config(path).network.resolve_proxy(True) == config.network.resolve_proxy(True)


def test_whole_discord_url_reference_with_separate_credentials_requires_consolidation(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_PROXY", "http://localhost:7890")
    original = {"channels": {"discord": {"proxy": "${DISCORD_PROXY}", "proxyUsername": "alice", "proxyPassword": "secret-password"}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ConfigLoadError, match="one full URL environment variable") as caught:
        load_config(path)
    assert "secret-password" not in str(caught.value)
    assert json.loads(path.read_text(encoding="utf-8")) == original
    original["network"] = {"proxy": "${SHARED_PROXY}"}
    path.write_text(json.dumps(original), encoding="utf-8")
    config = load_config(path)
    assert config.network.proxy == "${SHARED_PROXY}"
    assert config.channels.discord == {"useProxy": True}
