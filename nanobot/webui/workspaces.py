"""Persisted WebUI project workspace state."""

from __future__ import annotations

import json
import os
import platform
import socket
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
    WorkspaceScopeResolver,
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
        "recent_projects": [],
        "favorite_projects": [],
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
    for key, limit in (("recent_projects", 20), ("favorite_projects", 40)):
        paths = raw.get(key)
        if isinstance(paths, list):
            state[key] = list(dict.fromkeys(
                path for path in cast(list[object], paths)
                if isinstance(path, str) and "\0" not in path and Path(path).is_absolute()
            ))[:limit]
    return state


def remember_webui_project(path: Path) -> None:
    state = read_webui_workspace_state()
    recent = [str(path), *(item for item in state["recent_projects"] if item != str(path))][:20]
    if recent != state["recent_projects"]:
        state["recent_projects"] = recent
        try:
            write_webui_workspace_state(state)
        except OSError:
            logger.exception("failed to save recent WebUI projects")


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
    can_change_project: bool,
    can_use_full_access: bool,
) -> dict[str, Any]:
    state = read_webui_workspace_state()
    default_access_mode = state["default_access_mode"]
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
        "host": {"name": socket.gethostname(), "platform": platform.system()},
        "favorite_projects": [
            {"name": Path(path).name or path, "path": path}
            for path in state["favorite_projects"]
        ],
        "recent_projects": [
            {"name": Path(path).name or path, "path": path}
            for path in state["recent_projects"]
        ],
        "controls": {
            "can_change_project": can_change_project,
            "can_use_full_access": can_use_full_access,
            "can_browse_directories": can_change_project,
            "can_resolve_project": can_change_project,
            "can_manage_favorites": can_change_project,
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

    def automation_scope(
        self, session_key: str, channel: str, message_metadata: dict[str, Any],
    ) -> WorkspaceScope:
        """Use the runtime's policy, not the browser's draft project selection."""
        data = self._sessions.read_session_metadata(session_key) if self._sessions else None
        return WorkspaceScopeResolver(
            self._default_workspace, self._default_restrict_to_workspace,
        ).for_turn(
            channel=channel, message_metadata=message_metadata,
            session_metadata=data.get("metadata", {}) if data else {},
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
        return self._scope_from_snapshot(data)

    async def async_scope_for_session_key(self, session_key: str) -> WorkspaceScope:
        draft = self._draft_scopes.get(session_key)
        if draft is not None:
            self._draft_scopes.move_to_end(session_key)
            return draft
        if self._sessions is None:
            return self.default_scope()
        data = await self._sessions.state.read_metadata(session_key)
        return self._scope_from_snapshot(data)

    def _scope_from_snapshot(self, data: dict[str, Any] | None) -> WorkspaceScope:
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
        can_change_project: bool,
        can_use_full_access: bool,
    ) -> dict[str, Any]:
        return workspaces_payload(
            default_workspace=self._default_workspace,
            default_restrict_to_workspace=self._default_restrict_to_workspace,
            can_change_project=can_change_project,
            can_use_full_access=can_use_full_access,
        )

    def resolve_project(self, path: object) -> dict[str, str]:
        """Validate and remember a selection without changing any chat's scope."""
        if not isinstance(path, str) or not path.strip():
            raise WorkspaceScopeError("project_path must be a nonempty string")
        scope = validate_workspace_scope_payload(
            {"project_path": path.strip(), "access_mode": "restricted"},
            default_workspace=self._default_workspace,
            default_restrict_to_workspace=self._default_restrict_to_workspace,
            source_channel=_WEBUI_SCOPE_CHANNEL,
        )
        remember_webui_project(scope.project_path)
        return {"path": str(scope.project_path), "name": scope.project_name}

    def set_favorite_project(self, path: object, pinned: object) -> list[dict[str, str]]:
        """Pin validated folders; allow removing a favorite after it is deleted."""
        if not isinstance(path, str) or not path.strip() or "\0" in path:
            raise WorkspaceScopeError("path must be a nonempty directory path")
        if not isinstance(pinned, bool):
            raise WorkspaceScopeError("pinned must be a boolean")
        path = path.strip()
        if pinned:
            scope = validate_workspace_scope_payload(
                {"project_path": path, "access_mode": "restricted"},
                default_workspace=self._default_workspace,
                default_restrict_to_workspace=self._default_restrict_to_workspace,
                source_channel=_WEBUI_SCOPE_CHANNEL,
            )
            path = str(scope.project_path)
        state = read_webui_workspace_state()
        favorites: list[str] = state["favorite_projects"]
        existing = next((item for item in favorites if os.path.normcase(item) == os.path.normcase(path)), None)
        if pinned and existing is None:
            if len(favorites) >= 40:
                raise WorkspaceScopeError("at most 40 favorite folders can be pinned")
            favorites.append(path)
            write_webui_workspace_state(state)
        elif not pinned and existing is not None:
            favorites.remove(existing)
            write_webui_workspace_state(state)
        return [{"name": Path(item).name or item, "path": item} for item in favorites]

    async def scope_from_envelope(
        self,
        envelope: dict[str, Any],
        *,
        session_key: str | None,
        can_change_project: bool,
        can_use_full_access: bool,
    ) -> WorkspaceScope:
        current = (
            await self.async_scope_for_session_key(session_key)
            if session_key
            else self.default_scope()
        )
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
        if not can_change_project and not _scope_change_is_non_escalating(current, scope):
            raise WorkspaceScopeError(
                "project selection is unavailable for this connection",
                status=403,
            )
        if (
            not can_use_full_access
            and scope.access_mode == "full"
            and (
                current.access_mode != "full"
                or scope.project_path != current.project_path
            )
        ):
            raise WorkspaceScopeError(
                "full workspace access is unavailable for this connection",
                status=403,
            )
        return scope

    async def scope_for_new_chat(
        self,
        envelope: dict[str, Any],
        *,
        can_change_project: bool,
        can_use_full_access: bool,
    ) -> WorkspaceScope:
        return await self.scope_from_envelope(
            envelope,
            session_key=None,
            can_change_project=can_change_project,
            can_use_full_access=can_use_full_access,
        )

    async def scope_for_set_request(
        self,
        envelope: dict[str, Any],
        *,
        chat_id: str,
        chat_running: bool,
        can_change_project: bool,
        can_use_full_access: bool,
    ) -> WorkspaceScope:
        if chat_running:
            raise WorkspaceScopeError("chat_running", status=409)
        return await self.scope_from_envelope(
            envelope,
            session_key=webui_session_key(chat_id),
            can_change_project=can_change_project,
            can_use_full_access=can_use_full_access,
        )

    async def scope_for_message(
        self,
        envelope: dict[str, Any],
        *,
        chat_id: str,
        chat_running: bool,
        can_change_project: bool,
        can_use_full_access: bool,
    ) -> WorkspaceScope:
        scope = await self.scope_from_envelope(
            envelope,
            session_key=webui_session_key(chat_id),
            can_change_project=can_change_project,
            can_use_full_access=can_use_full_access,
        )
        if (
            WORKSPACE_SCOPE_METADATA_KEY in envelope
            and chat_running
            and scope.metadata()
            != (await self.async_scope_for_session_key(webui_session_key(chat_id))).metadata()
        ):
            raise WorkspaceScopeError("chat_running", status=409)
        return scope

    async def persist_scope(
        self,
        chat_id: str,
        scope: WorkspaceScope,
        *,
        session_key: str | None = None,
        expected_generation: str | None = None,
    ) -> tuple[str | None, bool]:
        session_key = session_key or webui_session_key(chat_id)
        generation = expected_generation
        created = False
        if self._sessions is not None:
            generation, created = await self._sessions.state.open_with_metadata(
                session_key,
                {"webui": True, WORKSPACE_SCOPE_METADATA_KEY: scope.metadata()},
                expected_generation=generation,
            )
        self._draft_scopes.pop(session_key, None)
        remember_webui_project(scope.project_path)
        return generation, created

    async def rollback_scope_admission(
        self,
        session_key: str,
        generation: str | None,
        *,
        created: bool,
    ) -> None:
        """Remove a newly opened session when transport admission fails."""
        if not created or generation is None or self._sessions is None:
            return
        await self._sessions.state.delete(
            session_key,
            expected_generation=generation,
        )

    async def stage_scope(self, chat_id: str, scope: WorkspaceScope) -> None:
        """Keep a new chat's scope transient until its first accepted message."""
        session_key = webui_session_key(chat_id)
        if (
            self._sessions is not None
            and await self._sessions.state.read_metadata(session_key) is not None
        ):
            await self.persist_scope(chat_id, scope)
            return
        remember_webui_project(scope.project_path)
        self._draft_scopes[session_key] = scope
        self._draft_scopes.move_to_end(session_key)
        while len(self._draft_scopes) > _MAX_DRAFT_SCOPES:
            self._draft_scopes.popitem(last=False)

    def discard_draft_scope(self, session_key: str) -> bool:
        """Discard the staged scope for a chat that has not persisted yet."""
        return self._draft_scopes.pop(session_key, None) is not None
