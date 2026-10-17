import json
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nanobot.config import home as instance_home
from nanobot.config import loader
from nanobot.config.errors import ConfigLoadError
from nanobot.config.home import InstancePaths
from nanobot.config.paths import (
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_workspace_path,
    is_default_workspace,
)
from nanobot.config.schema import Config


@pytest.fixture(autouse=True)
def isolate_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(instance_home, "_home_path", None)
    monkeypatch.setattr(loader, "_current_config_path", None)
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))


@pytest.mark.parametrize("explicit_home,explicit_config", [(False, False), (True, False), (False, True), (True, True)])
def test_instance_path_selection_is_pure(tmp_path, explicit_home, explicit_config):
    home = tmp_path / "instance"
    config = tmp_path / "external" / "alternate.json"
    paths = InstancePaths.resolve(config if explicit_config else None, home=home if explicit_home else None)
    expected_home = home if explicit_home else config.parent if explicit_config else Path.home() / ".nanobot"
    assert paths.home == expected_home
    assert paths.config_path == (config if explicit_config else expected_home / "config.json")
    assert not expected_home.exists()
    with pytest.raises(FrozenInstanceError):
        paths.home = tmp_path


def test_config_symlink_only_changes_home_when_explicit(tmp_path, create_symlink):
    home = tmp_path / "instance"
    home.mkdir()
    target = tmp_path / "external" / "alternate.json"
    target.parent.mkdir()
    target.write_text("{}")
    create_symlink(home / "config.json", target)
    assert InstancePaths.resolve(home=home) == InstancePaths(home, target)
    assert InstancePaths.resolve(home / "config.json") == InstancePaths(target.parent, target)


@pytest.mark.parametrize("explicit_home", [False, True])
def test_runtime_dirs_follow_selected_home(tmp_path, explicit_home):
    config_file = tmp_path / "external" / "config.json"
    loader.set_config_path(config_file)
    home = tmp_path / "instance" if explicit_home else config_file.parent
    if explicit_home:
        instance_home.set_home_path(home)
    assert get_data_dir() == home
    assert get_runtime_subdir("cron") == home / "cron"
    assert get_cron_dir() == home / "cron"
    assert get_logs_dir() == home / "logs"
    assert get_media_dir() == home / "media"
    assert get_media_dir("telegram") == home / "media" / "telegram"
    assert get_cli_history_path() == home / "history" / "cli_history"
    assert get_legacy_sessions_dir() == home / "sessions"


@pytest.mark.parametrize("workspace", [None, "relative-workspace", "~/custom-workspace"])
def test_loaded_workspace_is_bound_to_home(tmp_path, workspace):
    source = tmp_path / "external.json"
    data = {} if workspace is None else {"agents": {"defaults": {"workspace": workspace}}}
    source.write_text(json.dumps(data))
    home = tmp_path / "instance"
    config = loader.load_config(source, home=home)
    expected = home / "workspace" if workspace is None else Path(workspace).expanduser()
    if not expected.is_absolute():
        expected = home / expected
    assert config.workspace_path == expected
    assert config.instance_home == home
    assert config.source_path == source
    assert json.loads(source.read_text()) == data
    assert not home.exists()


def test_config_snapshot_and_save_survive_selection_and_environment_copy(tmp_path, monkeypatch):
    home = tmp_path / "first"
    source = tmp_path / "external.json"
    source.write_text('{"agents":{"defaults":{"workspace":"${TEST_WORKSPACE}"}}}')
    monkeypatch.setenv("TEST_WORKSPACE", "relative-workspace")
    config = loader.load_config(source, home=home)
    instance_home.set_home_path(tmp_path / "second")
    loader.set_config_path(tmp_path / "second-config.json")
    resolved = loader.resolve_config_env_vars(config)
    assert resolved.runtime_data_dir == home
    assert resolved.workspace_path == home / "relative-workspace"
    assert resolved.source_path == source
    assert config.agents.defaults.workspace == "${TEST_WORKSPACE}"
    loader.save_config(config)
    assert json.loads(source.read_text(encoding="utf-8"))["agents"]["defaults"]["workspace"] == "${TEST_WORKSPACE}"
    assert not (tmp_path / "second-config.json").exists()
    assert not home.exists()


def test_direct_config_captures_selection_once(tmp_path):
    instance_home.set_home_path(tmp_path / "first")
    config = Config()
    instance_home.set_home_path(tmp_path / "second")
    assert config.runtime_data_dir == tmp_path / "first"
    assert config.workspace_path == tmp_path / "first" / "workspace"
    loader.save_config(config)
    assert (tmp_path / "first" / "config.json").is_file()
    assert not (tmp_path / "second").exists()


@pytest.mark.parametrize("workspace", ["", "   ", None, 12, "bad\u0000path"])
def test_invalid_persisted_workspace_is_a_config_error(tmp_path, workspace):
    source = tmp_path / "config.json"
    source.write_text(json.dumps({"agents": {"defaults": {"workspace": workspace}}}))
    with pytest.raises(ConfigLoadError) as caught:
        loader.load_config(source)
    assert "agents.defaults.workspace" in str(caught.value)


def test_empty_environment_workspace_is_a_config_error(tmp_path, monkeypatch):
    source = tmp_path / "config.json"
    source.write_text('{"agents":{"defaults":{"workspace":"${TEST_WORKSPACE}"}}}')
    monkeypatch.setenv("TEST_WORKSPACE", "")
    with pytest.raises(ConfigLoadError) as caught:
        loader.resolve_config_env_vars(loader.load_config(source))
    assert caught.value.path == source
    assert "agents.defaults.workspace" in str(caught.value)


def test_workspace_helpers_use_instance_default(tmp_path):
    instance_home.set_home_path(tmp_path / "instance")
    assert get_workspace_path() == tmp_path / "instance" / "workspace"
    assert get_workspace_path("~/custom-workspace") == Path.home() / "custom-workspace"
    assert is_default_workspace(None) is True
    assert is_default_workspace(tmp_path / "instance" / "workspace") is True
    assert is_default_workspace("~/custom-workspace") is False


def test_channel_login_probes_use_home_without_creating_paths(tmp_path):
    from nanobot.channels.linear.state import local_state_present as linear_present
    from nanobot.channels.weixin.state import local_state_present as weixin_present
    from nanobot.channels.whatsapp.state import local_state_present as whatsapp_present

    home = tmp_path / "instance"
    instance_home.set_home_path(home)
    loader.set_config_path(tmp_path / "external.json")
    assert not whatsapp_present({})
    assert not weixin_present({})
    assert not linear_present({})
    assert not home.exists()
    (home / "whatsapp-auth").mkdir(parents=True)
    (home / "whatsapp-auth" / "neonize.db").write_bytes(b"saved")
    (home / "weixin").mkdir()
    (home / "weixin" / "account.json").write_text('{"token":"saved"}')
    assert whatsapp_present({})
    assert weixin_present({})


def test_linear_login_probe_does_not_initialize_or_change_existing_database(tmp_path):
    from nanobot.channels.linear.state import local_state_present

    instance_home.set_home_path(tmp_path)
    path = tmp_path / "linear" / "state.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE installations (organization_id TEXT)")
        connection.execute("INSERT INTO installations VALUES ('team')")
    before = path.read_bytes()
    assert local_state_present({})
    assert path.read_bytes() == before
    assert sorted(child.name for child in path.parent.iterdir()) == ["state.sqlite3"]
