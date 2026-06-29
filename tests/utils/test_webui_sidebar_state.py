import json

from nanobot.webui.sidebar_state import (
    default_webui_sidebar_state,
    read_webui_sidebar_state,
    webui_sidebar_state_path,
    write_webui_sidebar_state,
)


def test_sidebar_state_defaults_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    state = read_webui_sidebar_state()

    assert state == default_webui_sidebar_state()
    assert webui_sidebar_state_path() == tmp_path / "webui" / "sidebar-state.json"


def test_sidebar_state_normalizes_old_or_partial_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    path = webui_sidebar_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pinned_keys": ["websocket:a", "websocket:a", "", 123],
                "archived_keys": ["websocket:b"],
                "title_overrides": {"websocket:a": "  Release notes  ", "bad": ""},
                "project_name_overrides": {"/repo": "  Core  ", "bad": ""},
                "tags_by_key": {"websocket:a": ["work", "work", ""]},
                "collapsed_groups": {"Earlier": 1},
                "view": {"density": "tiny", "show_archived": True, "sort": "nope"},
            }
        ),
        encoding="utf-8",
    )

    state = read_webui_sidebar_state()

    assert state["schema_version"] == 1
    assert state["pinned_keys"] == ["websocket:a"]
    assert state["archived_keys"] == ["websocket:b"]
    assert state["title_overrides"] == {"websocket:a": "Release notes"}
    assert state["project_name_overrides"] == {"/repo": "Core"}
    assert state["tags_by_key"] == {"websocket:a": ["work"]}
    assert state["collapsed_groups"] == {"Earlier": True}
    assert state["view"] == {
        "density": "comfortable",
        "show_previews": False,
        "show_timestamps": True,
        "show_archived": True,
        "sort": "updated_desc",
    }


def test_sidebar_state_write_is_scoped_to_config_data_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    state = write_webui_sidebar_state(
        {
            "pinned_keys": ["websocket:a"],
            "archived_keys": ["websocket:b"],
            "title_overrides": {"websocket:a": "Release"},
            "project_name_overrides": {"/repo": "Core"},
            "view": {"density": "compact", "show_previews": True},
        }
    )

    assert state["pinned_keys"] == ["websocket:a"]
    assert state["archived_keys"] == ["websocket:b"]
    assert state["title_overrides"] == {"websocket:a": "Release"}
    assert state["project_name_overrides"] == {"/repo": "Core"}
    assert state["view"]["density"] == "compact"
    assert state["view"]["show_previews"] is True
    assert webui_sidebar_state_path().is_file()
    assert read_webui_sidebar_state()["pinned_keys"] == ["websocket:a"]
