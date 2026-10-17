"""Configuration reads and explicit runtime network policy activation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.model_presets import load_model_preset_catalog
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import load_config, resolve_ssrf_whitelist, save_config
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.nanobot import Nanobot
from nanobot.providers.factory import build_unconfigured_provider_snapshot, load_provider_snapshot
from nanobot.security.network import configure_ssrf_whitelist, validate_url_target
from nanobot.webui.settings_api import SettingsOperations
from nanobot.webui.settings_services import WebUISettingsServices

_PRIVATE_URL = "http://10.23.45.67/api"


@pytest.fixture(autouse=True)
def _isolate_network_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.security.network._allowed_networks", [])


def _config(tmp_path: Path, whitelist: list[str]) -> Config:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.provider = "openai"
    config.agents.defaults.model = "gpt-4o"
    config.providers.openai.api_key = "fixture-key"
    config.tools.ssrf_whitelist = whitelist
    return config


@pytest.mark.parametrize(
    ("active_whitelist", "stored_whitelist", "allowed"),
    [(["10.0.0.0/8"], [], True), ([], ["10.0.0.0/8"], False)],
)
def test_config_and_settings_reads_and_writes_preserve_active_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active_whitelist: list[str],
    stored_whitelist: list[str],
    allowed: bool,
) -> None:
    config_path = tmp_path / "other" / "config.json"
    config = _config(tmp_path, stored_whitelist)
    save_config(config, config_path)
    configure_ssrf_whitelist(active_whitelist)

    assert load_config(config_path).tools.ssrf_whitelist == stored_whitelist
    assert load_config(tmp_path / "absent.json").tools.ssrf_whitelist == []
    assert "default" in load_model_preset_catalog(config_path)
    services = WebUISettingsServices.create(config_path)
    assert services.config.load().agents.defaults.model == "gpt-4o"
    assert SettingsOperations(services.config).payload()["agent"]["model"] == "gpt-4o"
    services.config.update(lambda candidate: setattr(candidate.api, "port", 19001))
    assert load_config(config_path).api.port == 19001
    assert validate_url_target(_PRIVATE_URL)[0] is allowed

    before = config_path.read_bytes()

    def fail_write(*_args, **_kwargs) -> None:
        raise OSError("fixture write failure")

    monkeypatch.setattr("nanobot.config.loader.write_text_atomic", fail_write)
    with pytest.raises(OSError, match="fixture write failure"):
        services.config.update(lambda candidate: setattr(candidate.api, "port", 19002))

    assert config_path.read_bytes() == before
    assert validate_url_target(_PRIVATE_URL)[0] is allowed


@pytest.mark.asyncio
async def test_sdk_initialization_selects_policy_and_empty_whitelist_resets_it(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    save_config(_config(tmp_path, ["10.0.0.0/8"]), config_path)
    first = Nanobot.from_config(config_path)
    try:
        assert validate_url_target(_PRIVATE_URL)[0]
        save_config(_config(tmp_path, []), config_path)
        second = Nanobot.from_config(config_path)
        try:
            assert not validate_url_target(_PRIVATE_URL)[0]
        finally:
            await second.aclose()
    finally:
        await first.aclose()


def test_failed_sdk_initialization_keeps_active_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = _config(tmp_path, [])
    missing = "NANOBOT_TEST_POLICY_MISSING_KEY"
    monkeypatch.delenv(missing, raising=False)
    config.providers.openai.api_key = f"${{{missing}}}"
    save_config(config, config_path)
    configure_ssrf_whitelist(["10.0.0.0/8"])

    with pytest.raises(ConfigLoadError):
        Nanobot.from_config(config_path)

    assert validate_url_target(_PRIVATE_URL)[0]


def test_policy_env_resolution_ignores_unrelated_missing_credentials_and_keeps_raw_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    cidr_env = "NANOBOT_TEST_POLICY_CIDR"
    missing = "NANOBOT_TEST_POLICY_UNRELATED_CREDENTIAL"
    monkeypatch.setenv(cidr_env, "10.0.0.0/8")
    monkeypatch.delenv(missing, raising=False)
    config = _config(tmp_path, [f"${{{cidr_env}}}"])
    config.providers.openai.api_key = f"${{{missing}}}"
    save_config(config, config_path)

    raw = load_config(config_path)
    assert resolve_ssrf_whitelist(raw, config_path=config_path) == ["10.0.0.0/8"]
    assert raw.tools.ssrf_whitelist == [f"${{{cidr_env}}}"]
    assert load_config(config_path).providers.openai.api_key == f"${{{missing}}}"
    assert not validate_url_target(_PRIVATE_URL)[0]

    monkeypatch.delenv(cidr_env)
    configure_ssrf_whitelist(["10.0.0.0/8"])
    with pytest.raises(ConfigLoadError) as exc_info:
        resolve_ssrf_whitelist(raw, config_path=config_path)

    assert exc_info.value.path == config_path
    assert exc_info.value.kind == "missing_env"
    assert exc_info.value.issues[0].path == ("tools", "ssrfWhitelist", 0)
    assert validate_url_target(_PRIVATE_URL)[0]


@pytest.mark.asyncio
async def test_runtime_refresh_applies_whitelist_without_provider_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = _config(tmp_path, ["10.0.0.0/8"])
    save_config(config, config_path)
    loop = AgentLoop.from_config(
        config,
        tool_registry=ToolRegistry(),
        provider_snapshot_loader=lambda: load_provider_snapshot(config_path),
    )
    try:
        loop.refresh_runtime_config()
        signature = loop.runtime_resolver.provider_signature
        current = loop.runtime_resolver.runtime
        assert validate_url_target(_PRIVATE_URL)[0]
        config.tools.ssrf_whitelist = []
        save_config(config, config_path)
        assert validate_url_target(_PRIVATE_URL)[0]

        loop.refresh_runtime_config()

        assert loop.runtime_resolver.provider_signature == signature
        assert loop.runtime_resolver.runtime is current
        assert not validate_url_target(_PRIVATE_URL)[0]
    finally:
        await loop.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boot_whitelist", "live_whitelist", "allowed"),
    [(["10.0.0.0/8"], [], False), ([], ["10.0.0.0/8"], True)],
)
async def test_unconfigured_provider_fallback_keeps_last_successful_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boot_whitelist: list[str],
    live_whitelist: list[str],
    allowed: bool,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    boot = _config(tmp_path, boot_whitelist)
    boot.providers.openai.api_key = ""
    save_config(boot, config_path)
    initial = build_unconfigured_provider_snapshot(boot, "Provider setup incomplete")
    failures: list[str] = []

    def reload_provider():
        try:
            return load_provider_snapshot(config_path)
        except ValueError as exc:
            failures.append(str(exc))
            return build_unconfigured_provider_snapshot(boot, str(exc))

    registry = ToolRegistry()
    loop = AgentLoop.from_config(
        boot,
        provider=initial.provider,
        provider_signature=initial.signature,
        tool_registry=registry,
        provider_snapshot_loader=reload_provider,
    )
    mcp = MCPProvider({}, registry)
    try:
        live = boot.model_copy(deep=True)
        live.tools.ssrf_whitelist = live_whitelist
        save_config(live, config_path)
        assert (await mcp.reload())["ok"]
        assert validate_url_target(_PRIVATE_URL)[0] is allowed

        loop.refresh_runtime_config()

        assert failures
        assert validate_url_target(_PRIVATE_URL)[0] is allowed
    finally:
        await mcp.aclose()
        await loop.aclose()


@pytest.mark.asyncio
async def test_failed_active_preset_refresh_keeps_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = _config(tmp_path, ["10.0.0.0/8"])
    config.model_presets["fast"] = ModelPresetConfig(model="gpt-4o-mini", provider="openai")
    save_config(config, config_path)
    loop = AgentLoop.from_config(
        config,
        tool_registry=ToolRegistry(),
        provider_snapshot_loader=lambda **kwargs: load_provider_snapshot(config_path, **kwargs),
        preset_catalog_loader=lambda: load_model_preset_catalog(config_path),
    )
    try:
        loop.refresh_runtime_config()
        loop.set_model_preset("fast")
        current = loop.runtime_resolver.runtime
        config.tools.ssrf_whitelist = []
        del config.model_presets["fast"]
        save_config(config, config_path)

        with pytest.raises(KeyError, match="fast"):
            loop.refresh_runtime_config()

        assert loop.runtime_resolver.runtime is current
        assert validate_url_target(_PRIVATE_URL)[0]
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_mcp_reload_applies_policy_without_server_changes_and_preserves_it_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = _config(tmp_path, ["10.0.0.0/8"])
    save_config(config, config_path)
    provider = MCPProvider({}, ToolRegistry())
    try:
        assert (await provider.reload())["ok"]
        assert validate_url_target(_PRIVATE_URL)[0]
        config_path.write_text("{invalid JSON", encoding="utf-8")
        assert not (await provider.reload())["ok"]
        assert validate_url_target(_PRIVATE_URL)[0]

        config.tools.ssrf_whitelist = []
        missing = "NANOBOT_TEST_POLICY_MISSING_MCP_ENV"
        monkeypatch.delenv(missing, raising=False)
        config.providers.openai.api_key = f"${{{missing}}}"
        save_config(config, config_path)
        assert not (await provider.reload())["ok"]
        assert validate_url_target(_PRIVATE_URL)[0]

        config.providers.openai.api_key = "fixture-key"
        save_config(config, config_path)
        result = await provider.reload()
        assert result["ok"]
        assert result["added"] == result["removed"] == result["changed"] == []
        assert not validate_url_target(_PRIVATE_URL)[0]
    finally:
        await provider.aclose()
