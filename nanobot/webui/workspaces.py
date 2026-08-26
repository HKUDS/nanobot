"""Persisted WebUI project workspace state."""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.security.workspace_access import (
    WORKSPACE_SCOPE_METADATA_KEY,
    WorkspaceScope,
    WorkspaceScopeError,
    build_workspace_scope,
    default_workspace_scope,
    validate_workspace_scope_payload,
)
from nanobot.webui.session_identity import webui_session_key

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager

WEBUI_WORKSPACE_STATE_SCHEMA_VERSION = 1
_MAX_STATE_FILE_BYTES = 128 * 1024
_DEFAULT_ACCESS_MODES = {"default", "full"}
_LEGACY_RESTRICTED_DEFAULT_ACCESS_MODE = "restricted"
_WEBUI_SCOPE_CHANNEL = "websocket"
_MAX_DRAFT_SCOPES = 128


def _scope_change_is_non_escalating(current: WorkspaceScope, requested: WorkspaceScope) -> bool:
    """Allow a remote request only when it keeps the project and does not add access."""
    return (
        requested.project_path == current.project_path
        and (not current.restrict_to_workspace or requested.restrict_to_workspace)
    )


def webui_workspace_state_path() -> Path:
    return get_webui_dir() / "workspace-state.json"


def default_webui_workspace_state() -> dict[str, Any]:
    return {
        "schema_version": WEBUI_WORKSPACE_STATE_SCHEMA_VERSION,
        "default_access_mode": "default",
        "updated_at": None,
    }


def normalize_webui_workspace_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    raw = cast(dict[str, Any], raw)
    state = default_webui_workspace_state()
    updated_at = raw.get("updated_at")
    state["updated_at"] = updated_at if isinstance(updated_at, str) else None
    default_access_mode = raw.get("default_access_mode")
    if default_access_mode in _DEFAULT_ACCESS_MODES:
        state["default_access_mode"] = default_access_mode
    return state


def read_webui_workspace_state() -> dict[str, Any]:
    path = webui_workspace_state_path()
    if not path.is_file():
        return default_webui_workspace_state()
    try:
        if path.stat().st_size > _MAX_STATE_FILE_BYTES:
            logger.warning("webui workspace state too large, ignoring: {}", path)
            return default_webui_workspace_state()
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("read webui workspace state failed {}: {}", path, e)
        return default_webui_workspace_state()
    return normalize_webui_workspace_state(raw)


def write_webui_workspace_state(raw: dict[str, Any]) -> dict[str, Any]:
    state = normalize_webui_workspace_state(raw)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    encoded = json.dumps(
        state,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_STATE_FILE_BYTES:
        raise ValueError("workspace state is too large")

    path = webui_workspace_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "wb") as f:
        f.write(encoded)
        f.write(b"\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return state
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return state


def read_webui_default_access_mode() -> str:
    state = read_webui_workspace_state()
    mode = state.get("default_access_mode")
    return mode if mode in _DEFAULT_ACCESS_MODES else "default"


def write_webui_default_access_mode(mode: str) -> bool:
    if mode == _LEGACY_RESTRICTED_DEFAULT_ACCESS_MODE:
        mode = "default"
    if mode not in _DEFAULT_ACCESS_MODES:
        raise ValueError("default access mode must be default or full")
    state = read_webui_workspace_state()
    changed = state.get("default_access_mode") != mode
    if changed:
        state["default_access_mode"] = mode
        write_webui_workspace_state(state)
    return changed


def default_scope_for_webui(
    default_workspace: Path,
    default_restrict_to_workspace: bool,
) -> WorkspaceScope:
    mode = read_webui_default_access_mode()
    if mode == "default":
        return default_workspace_scope(
            default_workspace,
            default_restrict_to_workspace,
            source_channel=_WEBUI_SCOPE_CHANNEL,
        )
    return build_workspace_scope(default_workspace, mode, source_channel=_WEBUI_SCOPE_CHANNEL)


def workspaces_payload(
    *,
    default_workspace: Path,
    default_restrict_to_workspace: bool,
    controls_available: bool,
    folder_picker_available: bool = False,
) -> dict[str, Any]:
    default_access_mode = read_webui_default_access_mode()
    default_scope = (
        default_workspace_scope(
            default_workspace,
            default_restrict_to_workspace,
            source_channel=_WEBUI_SCOPE_CHANNEL,
        )
        if default_access_mode == "default"
        else build_workspace_scope(default_workspace, default_access_mode, source_channel=_WEBUI_SCOPE_CHANNEL)
    )
    return {
        "schema_version": WEBUI_WORKSPACE_STATE_SCHEMA_VERSION,
        "default_access_mode": default_access_mode,
        "default_scope": default_scope.payload(),
        "controls": {
            "can_change_project": controls_available,
            "can_use_full_access": controls_available,
            "can_pick_folder": folder_picker_available,
        },
    }


class WebUIWorkspaceController:
    """Own WebUI project scope persistence and validation."""

    def __init__(
        self,
        *,
        session_manager: SessionManager | None,
        default_workspace: Path,
        default_restrict_to_workspace: bool,
    ) -> None:
        self._sessions = session_manager
        self._default_workspace = default_workspace
        self._default_restrict_to_workspace = default_restrict_to_workspace
        self._draft_scopes: OrderedDict[str, WorkspaceScope] = OrderedDict()

    def default_scope(self) -> WorkspaceScope:
        return default_scope_for_webui(
            self._default_workspace,
            self._default_restrict_to_workspace,
        )

    def restricted_default_scope(self) -> WorkspaceScope:
        """Return the default workspace with access restricted for this request."""
        return build_workspace_scope(
            self._default_workspace,
            "restricted",
            source_channel=_WEBUI_SCOPE_CHANNEL,
        )

    def _scope_from_metadata_value(
        self,
        raw_scope: object,
        *,
        default_scope: WorkspaceScope | None = None,
    ) -> WorkspaceScope:
        try:
            return validate_workspace_scope_payload(
                raw_scope,
                default_workspace=self._default_workspace,
                default_restrict_to_workspace=self._default_restrict_to_workspace,
                source_channel=_WEBUI_SCOPE_CHANNEL,
            )
        except WorkspaceScopeError:
            return default_scope if default_scope is not None else self.default_scope()

    def scope_for_indexed_metadata(
        self,
        raw_scope: object,
        *,
        scope_present: bool,
        default_scope: WorkspaceScope,
    ) -> WorkspaceScope:
        """Resolve a sidebar-only metadata snapshot without an authority-store read."""
        if not scope_present:
            return default_scope
        return self._scope_from_metadata_value(raw_scope, default_scope=default_scope)

    def scope_for_session_key(self, session_key: str) -> WorkspaceScope:
        draft = self._draft_scopes.get(session_key)
        if draft is not None:
            self._draft_scopes.move_to_end(session_key)
            return draft
        if self._sessions is None:
            return self.default_scope()
        data = self._sessions.read_session_metadata(session_key)
        if not isinstance(data, dict):
            return self.default_scope()
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict) or WORKSPACE_SCOPE_METADATA_KEY not in metadata:
            return self.default_scope()
        metadata_data = cast(dict[str, Any], metadata)
        return self._scope_from_metadata_value(
            cast(object, metadata_data.get(WORKSPACE_SCOPE_METADATA_KEY))
        )

    def payload(
        self,
        *,
        controls_available: bool,
        folder_picker_available: bool = False,
    ) -> dict[str, Any]:
        return workspaces_payload(
            default_workspace=self._default_workspace,
            default_restrict_to_workspace=self._default_restrict_to_workspace,
            controls_available=controls_available,
            folder_picker_available=folder_picker_available,
        )

    def scope_from_envelope(
        self,
        envelope: dict[str, Any],
        *,
        session_key: str | None,
        controls_available: bool,
    ) -> WorkspaceScope:
        current = self.scope_for_session_key(session_key) if session_key else self.default_scope()
        raw = envelope.get(WORKSPACE_SCOPE_METADATA_KEY)
        if raw is None:
            scope = current
        else:
            scope = validate_workspace_scope_payload(
                raw,
                default_workspace=self._default_workspace,
                default_restrict_to_workspace=self._default_restrict_to_workspace,
                source_channel=_WEBUI_SCOPE_CHANNEL,
            )
        if not controls_available and not _scope_change_is_non_escalating(current, scope):
            raise WorkspaceScopeError("workspace controls are localhost-only", status=403)
        return scope

    def scope_for_new_chat(
        self,
        envelope: dict[str, Any],
        *,
        controls_available: bool,
    ) -> WorkspaceScope:
        return self.scope_from_envelope(
            envelope,
            session_key=None,
            controls_available=controls_available,
        )

    def scope_for_set_request(
        self,
        envelope: dict[str, Any],
        *,
        chat_id: str,
        chat_running: bool,
        controls_available: bool,
    ) -> WorkspaceScope:
        if chat_running:
            raise WorkspaceScopeError("chat_running", status=409)
        return self.scope_from_envelope(
            envelope,
            session_key=webui_session_key(chat_id),
            controls_available=controls_available,
        )

    def scope_for_message(
        self,
        envelope: dict[str, Any],
        *,
        chat_id: str,
        chat_running: bool,
        controls_available: bool,
    ) -> WorkspaceScope:
        scope = self.scope_from_envelope(
            envelope,
            session_key=webui_session_key(chat_id),
            controls_available=controls_available,
        )
        if (
            WORKSPACE_SCOPE_METADATA_KEY in envelope
            and chat_running
            and scope.metadata() != self.scope_for_session_key(webui_session_key(chat_id)).metadata()
        ):
            raise WorkspaceScopeError("chat_running", status=409)
        return scope

    def persist_scope(self, chat_id: str, scope: WorkspaceScope) -> None:
        session_key = webui_session_key(chat_id)
        if self._sessions is not None:
            session = self._sessions.get_or_create(session_key)
            session.metadata["webui"] = True
            session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = scope.metadata()
            self._sessions.save(session)
        self._draft_scopes.pop(session_key, None)

    def stage_scope(self, chat_id: str, scope: WorkspaceScope) -> None:
        """Keep a new chat's scope transient until its first accepted message."""
        session_key = webui_session_key(chat_id)
        if (
            self._sessions is not None
            and self._sessions.read_session_metadata(session_key) is not None
        ):
            self.persist_scope(chat_id, scope)
            return
        self._draft_scopes[session_key] = scope
        self._draft_scopes.move_to_end(session_key)
        while len(self._draft_scopes) > _MAX_DRAFT_SCOPES:
            self._draft_scopes.popitem(last=False)
