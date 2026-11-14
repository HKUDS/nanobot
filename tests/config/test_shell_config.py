import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from nanobot.agent.tools.shell_config import ExecToolConfig
from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_exec_timing_defaults() -> None:
    config = Config().tools.exec

    assert config.max_runtime == 3600
    assert config.max_runtime_limit == 86400
    assert config.idle_timeout == 300
    assert config.idle_action == "report"
    assert config.timeout == config.max_runtime


@pytest.mark.parametrize("values", [
    {"maxRuntime": 172800, "maxRuntimeLimit": 14400, "idleTimeout": 90, "idleAction": "terminate"},
    {"max_runtime": 172800, "max_runtime_limit": 14400, "idle_timeout": 90, "idle_action": "terminate"},
    {"timeout": 172800, "maxRuntimeLimit": 14400, "idleTimeout": 90, "idleAction": "terminate"},
])
def test_exec_timing_aliases_and_serialization(values) -> None:
    config = ExecToolConfig.model_validate(values)
    dumped = config.model_dump(by_alias=True)

    assert config.max_runtime == 172800
    assert config.max_runtime_limit == 14400
    assert config.idle_timeout == 90
    assert config.idle_action == "terminate"
    assert dumped["maxRuntime"] == 172800
    assert dumped["maxRuntimeLimit"] == 14400
    assert dumped["idleTimeout"] == 90
    assert dumped["idleAction"] == "terminate"
    assert not {"timeout", "max_runtime", "max_runtime_limit", "idle_timeout", "idle_action"} & dumped.keys()
    assert ExecToolConfig.model_validate_json(config.model_dump_json(by_alias=True)) == config


@pytest.mark.parametrize("name", ["timeout", "maxRuntime", "max_runtime"])
@pytest.mark.parametrize("runtime", [0, 60, 3600, 172800])
def test_exec_runtime_does_not_raise_default_model_limit(name: str, runtime: int) -> None:
    config = ExecToolConfig.model_validate({name: runtime})

    assert config.max_runtime == runtime
    assert config.timeout == runtime
    assert config.max_runtime_limit == 86400


@pytest.mark.parametrize("name", ["maxRuntime", "max_runtime"])
def test_exec_rejects_simultaneous_legacy_and_canonical_runtime(name: str) -> None:
    with pytest.raises(ValidationError, match="not both"):
        Config.model_validate({"tools": {"exec": {"timeout": 60, name: 60}}})


@pytest.mark.parametrize("values", [
    {"maxRuntime": -1},
    {"timeout": -1},
    {"idleTimeout": -1},
    {"maxRuntime": 1.5},
    {"idleTimeout": 1.5},
    {"maxRuntimeLimit": 0},
    {"maxRuntimeLimit": -1},
    {"idleAction": "ignore"},
])
def test_exec_rejects_invalid_timing_configuration(values) -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"tools": {"exec": values}})


def test_exec_unlimited_default_keeps_a_positive_model_limit() -> None:
    config = ExecToolConfig(max_runtime=0, max_runtime_limit=1, idle_timeout=0)

    assert config.max_runtime == 0
    assert config.max_runtime_limit == 1
    assert config.idle_timeout == 0
    assert ExecToolConfig(max_runtime=1, max_runtime_limit=1).max_runtime == 1


def test_legacy_timeout_property_writes_canonical_runtime() -> None:
    config = ExecToolConfig()
    config.timeout = 42
    assert config.max_runtime == 42
    assert config.model_dump(by_alias=True)["maxRuntime"] == 42

    config.max_runtime = 0
    assert config.timeout == 0
    assert "timeout" not in config.model_dump()


def test_legacy_exec_config_loads_and_saves_canonical_fields(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tools": {"exec": {"timeout": 172800}}}), encoding="utf-8")

    config = load_config(path)
    save_config(config, path)
    restored = load_config(path).tools.exec
    saved = json.loads(path.read_text(encoding="utf-8"))["tools"]["exec"]

    assert restored.max_runtime == 172800
    assert restored.max_runtime_limit == 86400
    assert saved["maxRuntime"] == 172800
    assert saved["maxRuntimeLimit"] == 86400
    assert saved["idleTimeout"] == 300
    assert saved["idleAction"] == "report"
    assert "timeout" not in saved


@pytest.mark.parametrize("runtime", [0, 42, 14400])
def test_legacy_webui_timeout_editor_updates_canonical_runtime(tmp_path, runtime: int) -> None:
    from nanobot.webui.settings_api import update_runtime_config_settings

    path = tmp_path / "config.json"
    save_config(Config.model_validate({"tools": {"exec": {
        "maxRuntime": 7200, "maxRuntimeLimit": 14400,
        "idleTimeout": 90, "idleAction": "terminate",
    }}}), path)

    result = update_runtime_config_settings(
        {"tools.exec.timeout": runtime}, local_browser=True, config_path=path,
    )
    config = load_config(path).tools.exec

    assert config.max_runtime == runtime
    assert config.timeout == runtime
    assert config.max_runtime_limit == 14400
    assert config.idle_timeout == 90
    assert config.idle_action == "terminate"
    assert result["runtime_config"]["tools.exec.timeout"] == runtime
    assert result["requires_restart"]
    assert json.loads(path.read_text(encoding="utf-8"))["tools"]["exec"]["maxRuntime"] == runtime


@pytest.mark.parametrize(("file_name", "env_name"), [
    ("timeout", "TIMEOUT"),
    ("timeout", "MAX_RUNTIME"),
    ("maxRuntime", "TIMEOUT"),
])
def test_exec_runtime_source_precedence_survives_settings_saves(
    tmp_path, monkeypatch, file_name: str, env_name: str,
) -> None:
    from nanobot.webui.settings_api import update_agent_settings, update_runtime_config_settings

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tools": {"exec": {file_name: 60}}}), encoding="utf-8")
    monkeypatch.setenv(f"NANOBOT_TOOLS__EXEC__{env_name}", "90")
    assert load_config(path).tools.exec.max_runtime == 60

    result = update_runtime_config_settings(
        {"tools.exec.timeout": 42}, local_browser=True, config_path=path,
    )
    assert result["runtime_config"]["tools.exec.timeout"] == 42

    result = update_agent_settings({"timezone": ["Asia/Shanghai"]}, config_path=path)
    assert result["runtime_config"]["tools.exec.timeout"] == 42
    assert load_config(path).tools.exec.max_runtime == 42
    saved = json.loads(path.read_text(encoding="utf-8"))["tools"]["exec"]
    assert saved["maxRuntime"] == 42
    assert "timeout" not in saved


@pytest.mark.parametrize("source", ["file", "environment"])
def test_exec_load_rejects_runtime_aliases_from_the_same_source(tmp_path, monkeypatch, source):
    path = tmp_path / "config.json"
    data = {"tools": {"exec": {"timeout": 60, "maxRuntime": 90}}}
    if source == "file":
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        monkeypatch.setenv("NANOBOT_TOOLS", json.dumps(data["tools"]))

    with pytest.raises(ConfigLoadError):
        load_config(path)


def test_exec_runtime_source_precedence_covers_both_canonical_spellings(monkeypatch):
    monkeypatch.setenv("NANOBOT_TOOLS__EXEC", json.dumps({
        "maxRuntime": 90, "max_runtime": 120,
    }))

    config = Config.model_validate({"tools": {"exec": {"timeout": 60}}})

    assert config.tools.exec.max_runtime == 60


@pytest.mark.asyncio
async def test_my_exec_config_reports_configured_timing(tmp_path) -> None:
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.self import MyTool
    from nanobot.bus.queue import MessageBus

    config = Config.model_validate({"tools": {"exec": {
        "timeout": 172800, "idleTimeout": 0, "idleAction": "terminate",
    }}})
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        tools_config=config.tools, model="test-model",
    )
    tool = loop.tools.get("my")
    assert isinstance(tool, MyTool)

    expected = {
        "max_runtime": 172800, "max_runtime_limit": 86400,
        "idle_timeout": 0, "idle_action": "terminate", "timeout": 172800,
    }
    for key, value in expected.items():
        result = await tool.execute(action="check", key=f"exec_config.{key}")
        assert result == f"exec_config.{key}: {value!r}"
