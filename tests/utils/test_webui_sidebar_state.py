import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import nanobot.webui.sidebar_state as sidebar_state
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


def test_sidebar_state_normalizes_partial_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    path = webui_sidebar_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pinned_keys": ["websocket:a", "websocket:a", "", 123],
                "archived_keys": ["websocket:b"],
                "session_order": ["websocket:b", "websocket:a", "websocket:b"],
                "title_overrides": {"websocket:a": "  Release notes  ", "bad": ""},
                "project_name_overrides": {"/repo": "  Core  ", "bad": ""},
                "tags_by_key": {"websocket:a": ["work", "work", ""]},
                "collapsed_groups": {"Earlier": 1},
                "workbench": {
                    "version": 1,
                    "tabs": {
                        "tab:websocket:a": {
                            "explicit": True,
                            "title": "  Research  ",
                            "paneKeys": ["websocket:a", "websocket:b", "websocket:a"],
                            "layoutPaneKeys": ["websocket:b", "missing", "websocket:a"],
                            "layout": "invalid-layout",
                            "splitRatios": [0.4, 2, "bad", float("nan")],
                        },
                        "tab:websocket:b": {
                            "paneKeys": ["websocket:b", "websocket:c"],
                            "layout": "bsp",
                        },
                    },
                },
                "view": {"density": "tiny", "show_archived": True, "sort": "nope"},
            }
        ),
        encoding="utf-8",
    )

    state = read_webui_sidebar_state()

    assert state["schema_version"] == 1
    assert state["pinned_keys"] == ["websocket:a"]
    assert state["archived_keys"] == ["websocket:b"]
    assert state["session_order"] == ["websocket:b", "websocket:a"]
    assert state["title_overrides"] == {"websocket:a": "Release notes"}
    assert state["project_name_overrides"] == {"/repo": "Core"}
    assert state["tags_by_key"] == {"websocket:a": ["work"]}
    assert state["collapsed_groups"] == {"Earlier": True}
    assert state["workbench"] == {
        "version": 1,
        "tabs": {
            "tab:websocket:a": {
                "explicit": True,
                "title": "Research",
                "paneKeys": ["websocket:a", "websocket:b"],
                "layoutPaneKeys": ["websocket:b", "websocket:a"],
                "layout": "columns",
                "splitRatios": [0.4, 0.95],
            },
        },
    }
    assert state["view"] == {
        "density": "comfortable",
        "show_previews": False,
        "show_timestamps": False,
        "show_archived": True,
        "sort": "updated_desc",
    }


def test_sidebar_state_write_is_scoped_to_config_data_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    state = write_webui_sidebar_state(
        {
            "pinned_keys": ["websocket:a"],
            "archived_keys": ["websocket:b"],
            "session_order": ["websocket:b", "websocket:a"],
            "title_overrides": {"websocket:a": "Release"},
            "project_name_overrides": {"/repo": "Core"},
            "view": {"density": "compact", "show_previews": True, "sort": "manual"},
        }
    )

    assert state["pinned_keys"] == ["websocket:a"]
    assert state["archived_keys"] == ["websocket:b"]
    assert state["session_order"] == ["websocket:b", "websocket:a"]
    assert state["title_overrides"] == {"websocket:a": "Release"}
    assert state["project_name_overrides"] == {"/repo": "Core"}
    assert state["view"]["density"] == "compact"
    assert state["view"]["show_previews"] is True
    assert state["view"]["sort"] == "manual"
    assert webui_sidebar_state_path().is_file()
    assert read_webui_sidebar_state()["pinned_keys"] == ["websocket:a"]


def test_sidebar_state_persists_only_visible_workbench_groups(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    tabs = {
        f"tab:websocket:{index}": {
            "explicit": False,
            "paneKeys": [f"websocket:{index}"],
            "layoutPaneKeys": [f"websocket:{index}"],
            "layout": "columns",
            "splitRatios": [],
        }
        for index in range(2_000)
    }

    state = write_webui_sidebar_state({"workbench": {"version": 1, "tabs": tabs}})

    assert state["workbench"] == {"version": 1, "tabs": {}}
    assert webui_sidebar_state_path().stat().st_size < 2_048


def test_sidebar_state_requires_supported_workbench_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    state = write_webui_sidebar_state(
        {
            "workbench": {
                "version": 2,
                "tabs": {
                    "tab:websocket:a": {
                        "explicit": True,
                        "paneKeys": ["websocket:a"],
                    }
                },
            }
        }
    )

    assert state["workbench"] == {"version": 1, "tabs": {}}


def test_sidebar_state_serializes_concurrent_writes(monkeypatch) -> None:
    counter_lock = threading.Lock()
    active_writes = 0
    peak_writes = 0

    def fake_write(raw: dict[str, object]) -> dict[str, object]:
        nonlocal active_writes, peak_writes
        with counter_lock:
            active_writes += 1
            peak_writes = max(peak_writes, active_writes)
        time.sleep(0.01)
        with counter_lock:
            active_writes -= 1
        return raw

    monkeypatch.setattr(sidebar_state, "_write_webui_sidebar_state", fake_write)
    payloads = [{"write": index} for index in range(12)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(sidebar_state.write_webui_sidebar_state, payloads))

    assert results == payloads
    assert peak_writes == 1
