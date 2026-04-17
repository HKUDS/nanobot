from __future__ import annotations

from pathlib import Path

from nanobot.config.instances import discover_runtime_instances, find_runtime_instance


def _touch_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def test_discover_runtime_instances_from_standard_nanobot_dirs(
    tmp_path: Path, monkeypatch
) -> None:
    default_config = tmp_path / ".nanobot" / "config.json"
    local_config = tmp_path / ".nanobot-local" / "config.json"
    research_config = tmp_path / ".nanobot-research" / "config.json"
    _touch_config(default_config)
    _touch_config(local_config)
    _touch_config(research_config)

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("nanobot.config.instances.get_config_path", lambda: research_config)

    instances = discover_runtime_instances()

    assert sorted(instance.name for instance in instances) == ["default", "local", "research"]
    assert find_runtime_instance("research") is not None
    assert find_runtime_instance(".nanobot-local") is not None
    assert find_runtime_instance("nanobot-local") is not None
