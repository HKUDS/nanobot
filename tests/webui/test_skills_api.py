from pathlib import Path
from types import SimpleNamespace

import pytest

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
    monkeypatch.setattr("nanobot.webui.skills_api.load_config", lambda: config)
    monkeypatch.setattr("nanobot.webui.skills_api.save_config", saved.append)
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


def test_delete_webui_skill_only_deletes_workspace_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _write_skill(tmp_path, "custom-skill")
    config = _config("custom-skill")
    saved: list[object] = []
    monkeypatch.setattr("nanobot.webui.skills_api.load_config", lambda: config)
    monkeypatch.setattr("nanobot.webui.skills_api.save_config", saved.append)
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
