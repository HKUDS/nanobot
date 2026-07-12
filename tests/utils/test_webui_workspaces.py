import json

import pytest

from nanobot.security.workspace_access import WorkspaceScopeError, default_workspace_scope
from nanobot.session.manager import SessionManager
from nanobot.webui.workspaces import (
    WebUIWorkspaceController,
    read_webui_default_access_mode,
    read_webui_workspace_state,
    webui_workspace_state_path,
    workspaces_payload,
    write_webui_default_access_mode,
)


def test_workspace_state_defaults_when_file_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    state = read_webui_workspace_state()

    assert state["default_access_mode"] == "default"
    assert webui_workspace_state_path() == tmp_path / "webui" / "workspace-state.json"


def test_workspace_state_ignores_legacy_project_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    project = tmp_path / "project"
    project.mkdir()
    path = webui_workspace_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "recent_projects": [
                    {"project_path": str(project)},
                    {"project_path": str(tmp_path / "missing")},
                ],
                "last_scope": {
                    "project_path": str(project),
                    "access_mode": "full",
                },
            }
        ),
        encoding="utf-8",
    )

    state = read_webui_workspace_state()

    assert "recent_projects" not in state
    assert "last_scope" not in state
    assert state["default_access_mode"] == "default"


def test_workspace_payload_is_config_data_dir_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()

    payload = workspaces_payload(
        default_workspace=default,
        default_restrict_to_workspace=False,
        controls_available=True,
    )

    assert payload["default_scope"]["project_path"] == str(default.resolve())
    assert payload["default_scope"]["access_mode"] == "full"
    assert payload["default_access_mode"] == "default"
    assert payload["controls"]["can_change_project"] is True


def test_workspace_payload_hides_mutable_state_when_controls_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()

    payload = workspaces_payload(
        default_workspace=default,
        default_restrict_to_workspace=False,
        controls_available=False,
    )

    assert payload["default_scope"]["project_path"] == str(default.resolve())
    assert payload["controls"]["can_change_project"] is False
    assert payload["controls"]["can_use_full_access"] is False


def test_workspace_payload_uses_webui_default_access_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()

    assert write_webui_default_access_mode("full") is True
    assert write_webui_default_access_mode("full") is False

    payload = workspaces_payload(
        default_workspace=default,
        default_restrict_to_workspace=True,
        controls_available=True,
    )

    assert payload["default_access_mode"] == "full"
    assert payload["default_scope"]["project_path"] == str(default.resolve())
    assert payload["default_scope"]["access_mode"] == "full"


def test_legacy_restricted_webui_default_access_mode_maps_to_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")

    assert write_webui_default_access_mode("restricted") is False
    assert read_webui_default_access_mode() == "default"


def test_webui_default_access_applies_to_unscoped_old_sessions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    default.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    sessions.save(sessions.get_or_create("websocket:old-chat"))
    write_webui_default_access_mode("full")
    controller = WebUIWorkspaceController(
        session_manager=sessions,
        default_workspace=default,
        default_restrict_to_workspace=True,
    )

    scope = controller.scope_for_session_key("websocket:old-chat")
    new_scope = controller.scope_for_new_chat({}, controls_available=True)

    assert scope.project_path == default.resolve()
    assert scope.access_mode == "full"
    assert new_scope.access_mode == "full"


def test_webui_default_access_does_not_override_explicit_session_scope(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    project = tmp_path / "project"
    default.mkdir()
    project.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    controller = WebUIWorkspaceController(
        session_manager=sessions,
        default_workspace=default,
        default_restrict_to_workspace=True,
    )
    explicit = default_workspace_scope(project, restrict_to_workspace=False)
    controller.persist_scope("explicit-chat", explicit)

    scope = controller.scope_for_session_key("websocket:explicit-chat")

    assert scope.project_path == project.resolve()
    assert scope.access_mode == "full"


def test_scope_for_session_key_reads_metadata_without_full_history(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    project = tmp_path / "project"
    default.mkdir()
    project.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    controller = WebUIWorkspaceController(
        session_manager=sessions,
        default_workspace=default,
        default_restrict_to_workspace=True,
    )
    explicit = default_workspace_scope(project, restrict_to_workspace=False)
    controller.persist_scope("metadata-only", explicit)

    def fail_full_read(_key: str) -> None:
        raise AssertionError("scope lookup should not read full session history")

    monkeypatch.setattr(sessions, "read_session_file", fail_full_read)

    scope = controller.scope_for_session_key("websocket:metadata-only")

    assert scope.project_path == project.resolve()
    assert scope.access_mode == "full"


def test_remote_existing_chat_can_reduce_its_workspace_access(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    project = tmp_path / "project"
    default.mkdir()
    project.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    controller = WebUIWorkspaceController(
        session_manager=sessions,
        default_workspace=default,
        default_restrict_to_workspace=True,
    )
    controller.persist_scope(
        "remote-chat",
        default_workspace_scope(project, restrict_to_workspace=False),
    )

    scope = controller.scope_for_set_request(
        {
            "workspace_scope": {
                "project_path": str(project),
                "access_mode": "restricted",
            }
        },
        chat_id="remote-chat",
        chat_running=False,
        controls_available=False,
    )

    assert scope.project_path == project.resolve()
    assert scope.access_mode == "restricted"


@pytest.mark.parametrize(
    ("default_restricted", "project_name", "access_mode", "allowed"),
    [
        (False, "default", "restricted", True),
        (True, "default", "full", False),
        (False, "other", "restricted", False),
    ],
)
def test_remote_new_chat_only_allows_non_escalating_scope_change(
    tmp_path,
    monkeypatch,
    default_restricted: bool,
    project_name: str,
    access_mode: str,
    allowed: bool,
) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default = tmp_path / "default"
    other = tmp_path / "other"
    default.mkdir()
    other.mkdir()
    controller = WebUIWorkspaceController(
        session_manager=None,
        default_workspace=default,
        default_restrict_to_workspace=default_restricted,
    )
    requested_path = tmp_path / project_name

    def resolve():
        return controller.scope_for_new_chat(
            {
                "workspace_scope": {
                    "project_path": str(requested_path),
                    "access_mode": access_mode,
                }
            },
            controls_available=False,
        )

    if allowed:
        scope = resolve()
        assert scope.project_path == requested_path.resolve()
        assert scope.access_mode == access_mode
    else:
        with pytest.raises(WorkspaceScopeError, match="workspace controls are localhost-only"):
            resolve()
