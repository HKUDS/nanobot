from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.settings_api import update_runtime_config_settings
from nanobot.webui.settings_contracts import WebUISettingsError
from nanobot.webui.settings_runtime import (
    runtime_config_payload,
    update_runtime_config,
)


def test_web_proxy_roundtrip_while_disabled_preserves_model_proxy(tmp_path):
    path = tmp_path / "config.json"
    config = Config()
    config.tools.web.enable = False
    config.providers.openai.proxy = "http://model-proxy.example:8080"
    save_config(config, path)
    for proxy in ("http://web-proxy.example:7890", None):
        payload = update_runtime_config_settings({"tools.web.proxy": proxy}, local_browser=True, config_path=path)
        assert payload["runtime_config"]["tools.web.proxy"] == proxy
        assert payload["requires_restart"]
        saved = load_config(path)
        assert saved.tools.web.proxy == proxy
        assert saved.tools.web.enable is False
        assert saved.providers.openai.proxy == "http://model-proxy.example:8080"


def test_runtime_patch_persists_and_preserves_other_domains(tmp_path):
    path = tmp_path / "config.json"
    config = Config.model_validate({
        "providers": {"openai": {"apiKey": "${PRIVATE_API_KEY}"}},
        "channels": {"telegram": {"token": "keep-me", "streaming": False}},
    })
    save_config(config, path)
    payload = update_runtime_config_settings({
        "agents.defaults.max_tool_iterations": 71,
        "agents.defaults.timezone_mode": "manual",
        "agents.defaults.timezone": "Asia/Shanghai",
        "tools.exec.timeout": 0,
        "tools.exec.allowed_env_keys": ["MY_TOKEN"],
        "tools.image_generation.save_dir": "images",
    }, local_browser=True, config_path=path)
    saved = load_config(path)
    assert saved.agents.defaults.max_tool_iterations == 71
    assert saved.agents.defaults.timezone == "Asia/Shanghai"
    assert saved.tools.exec.timeout == 0
    assert saved.tools.exec.allowed_env_keys == ["MY_TOKEN"]
    assert saved.providers.openai.api_key == "${PRIVATE_API_KEY}"
    assert saved.channels.telegram == {"token": "keep-me", "streaming": False}
    assert payload["requires_restart"]
    assert payload["runtime_config"]["tools.image_generation.save_dir"] == "images"
    assert "api.api_key" not in runtime_config_payload(saved)
    assert "PRIVATE_API_KEY" not in json.dumps(runtime_config_payload(saved))


@pytest.mark.parametrize("values", [
    {"channels.telegram.token": "bad"},
    {"agents.defaults.workspace": "/not-editable-from-settings"},
    {"providers.openai.api_key": "bad"},
    {"tools.exec": {"enable": False}},
    {"agents.defaults.max_concurrent_subagents": 0},
    {"agents.defaults.max_tool_iterations": True},
    {"tools.exec.timeout": -1},
    {"tools.exec.timeout": 86401},
    {"tools.exec.timeout": "60"},
    {"tools.exec.enable": "false"},
    {"tools.exec.allowed_env_keys": "TOKEN"},
    {"tools.exec.allowed_env_keys": [3]},
    {"tools.exec.deny_patterns": ["["]},
    {"tools.ssrf_whitelist": ["not-a-network"]},
    {"tools.exec.sandbox": "unknown"},
    {"agents.defaults.dream.cron": "not a cron"},
    {"agents.defaults.dream.model_override": "missing"},
    {"agents.defaults.timezone_mode": "manual", "agents.defaults.timezone": "Mars/Olympus"},
    {"gateway.port": 65536},
    {"gateway.heartbeat.interval_s": 0},
    {"api.host": "192.168.1.2"},
    {"api.timeout": float("nan")},
    {"tools.image_generation.save_dir": ""},
    {"tools.image_generation.save_dir": "../outside"},
    {"tools.image_generation.save_dir": "C:/outside"},
    {"tools.image_generation.save_dir": "/outside"},
])
def test_invalid_patch_is_atomic(tmp_path, values):
    path = tmp_path / "config.json"
    save_config(Config(), path)
    before = path.read_bytes()
    with pytest.raises(WebUISettingsError):
        update_runtime_config_settings({
            "agents.defaults.max_tool_iterations": 71, **values,
        }, local_browser=True, config_path=path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("limit", [120, 86400, 172800])
def test_shell_runtime_editor_uses_the_configured_limit(tmp_path, limit):
    path = tmp_path / "config.json"
    config = Config.model_validate({"tools": {"exec": {"maxRuntimeLimit": limit}}})
    save_config(config, path)
    before = path.read_bytes()

    with pytest.raises(WebUISettingsError, match=f"1–{limit} seconds"):
        update_runtime_config_settings({"tools.exec.timeout": limit + 1}, config_path=path)
    assert path.read_bytes() == before

    payload = update_runtime_config_settings({"tools.exec.timeout": limit}, config_path=path)
    assert payload["advanced"]["exec_max_runtime_limit"] == limit
    assert payload["runtime_config"]["tools.exec.timeout"] == limit
    saved = load_config(path).tools.exec
    assert saved.max_runtime == limit
    assert saved.max_runtime_limit == limit


def test_other_settings_preserve_a_longer_trusted_shell_runtime(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config.model_validate({"tools": {"exec": {
        "maxRuntime": 172800, "maxRuntimeLimit": 86400,
    }}}), path)

    update_runtime_config_settings({"tools.exec.path_append": "extra-bin"}, config_path=path)

    saved = load_config(path).tools.exec
    assert saved.max_runtime == 172800
    assert saved.max_runtime_limit == 86400
    assert saved.path_append == "extra-bin"


def test_remote_client_cannot_change_install_policy():
    config = Config()
    with pytest.raises(WebUISettingsError) as error:
        update_runtime_config(config, {
            "tools.webui_allow_remote_package_install": True,
        }, local_browser=False)
    assert error.value.status == 403
    assert not config.tools.webui_allow_remote_package_install
    assert update_runtime_config(config, {
        "tools.webui_allow_remote_package_install": True,
    }, local_browser=True)


def test_timezone_auto_and_nullable_fields():
    config = Config.model_validate({"agents": {"defaults": {
        "timezoneMode": "manual", "timezone": "UTC", "dream": {"cron": "0 2 * * *"},
    }}})
    assert update_runtime_config(config, {
        "agents.defaults.timezone_mode": "auto",
        "tools.web.proxy": None,
    }, local_browser=True)
    assert config.agents.defaults.timezone_mode == "auto"
    assert config.agents.defaults.dream.cron == "0 2 * * *"
    assert not update_runtime_config(config, {}, local_browser=True)


def test_api_changes_require_explicit_restart(tmp_path):
    path = tmp_path / "config.json"
    payload = update_runtime_config_settings({"api.timeout": 222.5}, config_path=path)
    assert payload["api"]["timeout"] == 222.5
    assert payload["requires_restart"]


def test_runtime_payload_matches_shared_catalogue_contract():
    fixture = Path(__file__).with_name("fixtures") / "runtime-config-keys.json"
    paths = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(paths) == len(set(paths))
    assert set(runtime_config_payload(Config())) == set(paths)


def test_disabling_memory_consolidation_preserves_other_memory_settings():
    config = Config()
    before = config.agents.defaults.model_dump()
    assert update_runtime_config(config, {"agents.defaults.dream.enabled": False}, local_browser=True)
    after = config.agents.defaults.model_dump()
    before["dream"]["enabled"] = False
    assert after == before


@pytest.mark.parametrize("backend", ["bwrap", "seatbelt"])
def test_sandbox_backend_persists_with_path_permissions(tmp_path, backend):
    path = tmp_path / "config.json"
    payload = update_runtime_config_settings({
        "tools.exec.sandbox": backend,
        "tools.exec.sandbox_ro_binds": ["shared/read"],
        "tools.exec.sandbox_rw_binds": ["shared/write"],
    }, local_browser=True, config_path=path)
    saved = load_config(path).tools.exec
    assert saved.sandbox == backend
    assert saved.sandbox_ro_binds == ["shared/read"]
    assert saved.sandbox_rw_binds == ["shared/write"]
    assert payload["runtime_config"]["tools.exec.sandbox"] == backend
    assert payload["requires_restart"]
