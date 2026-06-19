"""Tests for CLI Apps loop helpers."""

from types import SimpleNamespace

from nanobot.apps.cli.service import CliAppManager
from nanobot.apps.cli.utils import runtime_lines, session_extra


def test_session_extra_returns_cli_apps_only_when_present() -> None:
    cli_apps = [{"name": "zoom"}]
    assert session_extra({"cli_apps": cli_apps}) == {"cli_apps": cli_apps}
    assert session_extra({}) == {}
    assert session_extra(None) == {}


def test_cli_app_mentions_inject_runtime_metadata(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr("nanobot.apps.cli.service.get_runtime_subdir", lambda _name: data_dir)
    manager = CliAppManager(workspace=tmp_path)
    manager._save_installed(
        {
            "zoom": {
                "entry_point": "cli-anything-zoom",
                "source": "harness",
            },
            "krita": {
                "entry_point": "cli-anything-krita",
                "source": "harness",
            },
        }
    )

    lines = runtime_lines(
        SimpleNamespace(content="please use @zoom tonight; ignore @krita?", metadata={}),
        tmp_path,
    )

    joined = "\n".join(lines)
    assert "CLI App Mention: @zoom" in joined
    assert "tool=run_cli_app" in joined
    assert "entry_point=cli-anything-zoom" in joined
    assert "skill=skills/cli-app-zoom/SKILL.md" in joined


def test_structured_cli_app_attachment_injects_runtime_metadata(tmp_path):
    lines = runtime_lines(
        SimpleNamespace(
            content="please use @zoom tonight",
            metadata={
                "cli_apps": [{
                    "name": "zoom",
                    "entry_point": "cli-anything-zoom",
                    "display_name": "Zoom",
                }],
            },
        ),
        tmp_path,
    )

    joined = "\n".join(lines)
    assert "CLI App Attachment: @zoom" in joined
    assert "tool=run_cli_app" in joined
    assert "entry_point=cli-anything-zoom" in joined
    assert "skill=skills/cli-app-zoom/SKILL.md" in joined
