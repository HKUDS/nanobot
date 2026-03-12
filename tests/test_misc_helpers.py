from __future__ import annotations

import importlib
import runpy
from pathlib import Path

import nanobot.skills
from nanobot.utils.helpers import (
    ensure_dir,
    get_data_path,
    get_sessions_path,
    get_skills_path,
    get_workspace_path,
    parse_session_key,
    safe_filename,
    timestamp,
    truncate_string,
)


def test_utils_paths_and_helpers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    data = get_data_path()
    ws_default = get_workspace_path()
    ws_custom = get_workspace_path("~/custom-ws")
    sessions = get_sessions_path()
    skills = get_skills_path(ws_default)

    assert data.exists()
    assert ws_default.exists()
    assert ws_custom.exists()
    assert sessions.exists()
    assert skills.exists()
    assert ensure_dir(tmp_path / "x").exists()

    assert truncate_string("hello", 10) == "hello"
    assert truncate_string("abcdefghij", 5, "..") == "abc.."
    assert safe_filename('a<b>:"/\\|?*') == "a_b________"
    assert "T" in timestamp()


def test_parse_session_key_validation() -> None:
    assert parse_session_key("cli:direct") == ("cli", "direct")
    try:
        parse_session_key("invalid")
        assert False, "expected ValueError"
    except ValueError:
        assert True


def test_skills_package_import_covered() -> None:
    mod = importlib.reload(nanobot.skills)
    assert mod.__all__ == []


def test_main_module_exec(monkeypatch) -> None:
    called = {"ok": False}

    def _fake_app() -> None:
        called["ok"] = True

    import nanobot.cli.commands as commands

    monkeypatch.setattr(commands, "app", _fake_app)
    runpy.run_module("nanobot.__main__", run_name="__main__")
    assert called["ok"] is True
