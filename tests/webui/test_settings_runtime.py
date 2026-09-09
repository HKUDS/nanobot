from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.settings_api import update_runtime_config_settings
from nanobot.webui.settings_contracts import WebUISettingsError
from nanobot.webui.settings_runtime import (
    RUNTIME_CONFIG_PATHS,
    runtime_config_payload,
    update_runtime_config,
)


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


def test_every_exposed_runtime_setting_has_a_frontend_control():
    fields = Path(__file__).parents[2] / "webui/src/components/settings/system/runtime-config-fields.ts"
    paths = re.findall(r'group: "[^"]+", path: "([^"]+)"', fields.read_text(encoding="utf-8"))
    assert len(paths) == len(set(paths))
    assert set(paths) == set(RUNTIME_CONFIG_PATHS)


def test_disabling_memory_consolidation_preserves_other_memory_settings():
    config = Config()
    before = config.agents.defaults.model_dump()
    assert update_runtime_config(config, {"agents.defaults.dream.enabled": False}, local_browser=True)
    after = config.agents.defaults.model_dump()
    before["dream"]["enabled"] = False
    assert after == before
