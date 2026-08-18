from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.skills_api import (
    SkillManagementError,
    delete_webui_skill,
    set_webui_skill_enabled,
    webui_skill_detail_payload,
    webui_skills_payload,
)


def _write_skill(workspace: Path, name: str, *, metadata: str = "") -> Path:
    directory = workspace / "skills" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} description.\n{metadata}---\n",
        encoding="utf-8",
    )
    return directory


def _config(*disabled: str) -> SimpleNamespace:
    return SimpleNamespace(
        agents=SimpleNamespace(
            defaults=SimpleNamespace(disabled_skills=list(disabled)),
        )
    )


def test_disabled_skills_remain_visible_and_loadable(tmp_path: Path) -> None:
    _write_skill(tmp_path, "custom-skill")

    payload = webui_skills_payload(tmp_path, disabled_skills={"custom-skill"})
    skill = next(item for item in payload["skills"] if item["name"] == "custom-skill")

    assert skill["enabled"] is False
    assert skill["deletable"] is True
    detail = webui_skill_detail_payload(
        tmp_path,
        "custom-skill",
        disabled_skills={"custom-skill"},
    )
    assert detail is not None
    assert detail["enabled"] is False
    assert "custom-skill description" in detail["raw_markdown"]


def test_skill_detail_exposes_copyable_install_commands(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "custom-skill",
        metadata=(
            'metadata: {"nanobot":{"requires":{"bins":["demo"]},'
            '"install":[{"id":"brew","kind":"brew","formula":"acme/demo",'
            '"label":"Install demo"}]}}\n'
        ),
    )

    detail = webui_skill_detail_payload(tmp_path, "custom-skill")

    assert detail is not None
    assert detail["install_options"] == [
        {
            "id": "brew",
            "kind": "brew",
            "label": "Install demo",
            "command": "brew install acme/demo",
        }
    ]


def test_set_webui_skill_enabled_persists_and_updates_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_skill(tmp_path, "custom-skill")
    config = _config()
    saved: list[object] = []
    monkeypatch.setattr("nanobot.webui.skills_api.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nanobot.webui.skills_api.save_config",
        lambda value, _path=None: saved.append(value),
    )
    disabled: set[str] = set()

    action = set_webui_skill_enabled(
        tmp_path,
        "custom-skill",
        enabled=False,
        disabled_skills=disabled,
    )

    assert action == {
        "name": "custom-skill",
        "enabled": False,
        "deleted": False,
    }
    assert config.agents.defaults.disabled_skills == ["custom-skill"]
    assert disabled == {"custom-skill"}
    assert saved == [config]


def test_skill_state_uses_explicit_gateway_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    _write_skill(workspace, "custom-skill")
    default_path = tmp_path / "default.json"
    gateway_path = tmp_path / "gateway.json"
    save_config(Config(), default_path)
    save_config(Config(), gateway_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", default_path)

    set_webui_skill_enabled(
        workspace,
        "custom-skill",
        enabled=False,
        disabled_skills=set(),
        config_path=gateway_path,
    )

    assert load_config(default_path).agents.defaults.disabled_skills == []
    assert load_config(gateway_path).agents.defaults.disabled_skills == ["custom-skill"]


def test_delete_webui_skill_only_deletes_workspace_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _write_skill(tmp_path, "custom-skill")
    config = _config("custom-skill")
    saved: list[object] = []
    monkeypatch.setattr("nanobot.webui.skills_api.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nanobot.webui.skills_api.save_config",
        lambda value, _path=None: saved.append(value),
    )
    disabled = {"custom-skill"}

    action = delete_webui_skill(
        tmp_path,
        "custom-skill",
        disabled_skills=disabled,
    )

    assert action["deleted"] is True
    assert not directory.exists()
    assert disabled == set()
    assert config.agents.defaults.disabled_skills == []
    assert saved == [config]

    with pytest.raises(SkillManagementError) as exc_info:
        delete_webui_skill(tmp_path, "cron", disabled_skills=disabled)
    assert exc_info.value.status == 403


def test_delete_webui_skill_rejects_symlinked_skills_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    directory = outside / "custom-skill"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: custom-skill\n---\n",
        encoding="utf-8",
    )
    try:
        (workspace / "skills").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    with pytest.raises(SkillManagementError) as exc_info:
        delete_webui_skill(workspace, "custom-skill", disabled_skills=set())

    assert exc_info.value.status == 403
    assert (outside / "custom-skill" / "SKILL.md").is_file()


def test_delete_webui_skill_restores_directory_when_config_save_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _write_skill(tmp_path, "custom-skill")
    config = _config("custom-skill")
    monkeypatch.setattr("nanobot.webui.skills_api.load_config", lambda _path=None: config)

    def fail_save(_config: object, _path: Path | None = None) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("nanobot.webui.skills_api.save_config", fail_save)
    disabled = {"custom-skill"}

    with pytest.raises(OSError, match="disk full"):
        delete_webui_skill(
            tmp_path,
            "custom-skill",
            disabled_skills=disabled,
        )

    assert directory.is_dir()
    assert (directory / "SKILL.md").is_file()
    assert config.agents.defaults.disabled_skills == ["custom-skill"]
    assert disabled == {"custom-skill"}
