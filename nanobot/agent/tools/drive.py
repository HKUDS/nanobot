"""Google Drive tool (service account + shared folder access)."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

from nanobot.agent.tools._google import (
    GoogleDeps,
    build_google_service,
    require_google_deps,
    resolve_credentials_path,
    service_account_email_hint,
)
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.drive_config import DriveToolConfig
from nanobot.agent.tools.path_utils import resolve_workspace_path
from nanobot.agent.tools.schema import (
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.security.workspace_policy import WorkspaceBoundaryError

_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_GOOGLE_APP_EXPORT: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "application/pdf",
    "application/vnd.google-apps.drawings": "application/pdf",
}
_SAFE_FILENAME = re.compile(r"[^\w.\- ]+", re.UNICODE)
_MAX_ANCESTOR_DEPTH = 100
_DRIVE_HTTP_TIMEOUT_SECONDS = 15.0
_LABEL = "Google Drive"


class _DriveFile(TypedDict, total=False):
    id: str
    name: str
    mimeType: str
    modifiedTime: str
    size: str
    parents: list[str]
    trashed: bool
    webViewLink: str


class _DriveRequest(Protocol):
    def execute(self) -> object: ...


class _DriveFilesResource(Protocol):
    def get(self, **kwargs: object) -> _DriveRequest: ...
    def list(self, **kwargs: object) -> _DriveRequest: ...
    def export(self, **kwargs: object) -> _DriveRequest: ...
    def get_media(self, **kwargs: object) -> _DriveRequest: ...


class _DriveService(Protocol):
    def files(self) -> _DriveFilesResource: ...




def _require_google_deps() -> GoogleDeps:
    return require_google_deps("Google Drive", "drive")


def _credentials_path(config: DriveToolConfig) -> Path:
    raw = (config.credentials_path or "").strip()
    if not raw:
        raw = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not raw:
        raise ValueError("Drive credentials_path is not configured")
    path = resolve_credentials_path(raw)
    if not path.is_file():
        raise ValueError(f"Drive credentials file not found: {path}")
    return path



def _response_mapping(value: object, operation: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Drive API returned an invalid {operation} response")
    raw = cast(Mapping[object, object], value)
    return {str(key): item for key, item in raw.items()}


def _file_mapping(value: object) -> _DriveFile | None:
    if not isinstance(value, Mapping):
        return None
    raw = cast(Mapping[object, object], value)
    result: _DriveFile = {}
    file_id = raw.get("id")
    name = raw.get("name")
    mime_type = raw.get("mimeType")
    modified_time = raw.get("modifiedTime")
    size = raw.get("size")
    web_view_link = raw.get("webViewLink")
    if isinstance(file_id, str):
        result["id"] = file_id
    if isinstance(name, str):
        result["name"] = name
    if isinstance(mime_type, str):
        result["mimeType"] = mime_type
    if isinstance(modified_time, str):
        result["modifiedTime"] = modified_time
    if isinstance(size, str):
        result["size"] = size
    if isinstance(web_view_link, str):
        result["webViewLink"] = web_view_link
    parents = raw.get("parents")
    if isinstance(parents, list):
        parent_values = cast(list[object], parents)
        if all(isinstance(item, str) for item in parent_values):
            result["parents"] = cast(list[str], parent_values)
    trashed = raw.get("trashed")
    if isinstance(trashed, bool):
        result["trashed"] = trashed
    return result


def _response_files(value: object) -> tuple[list[_DriveFile], str | None]:
    response = _response_mapping(value, "file list")
    raw_files = response.get("files")
    if not isinstance(raw_files, list):
        files: list[_DriveFile] = []
    else:
        files = [
            item
            for value in cast(list[object], raw_files)
            if (item := _file_mapping(value)) is not None
        ]
    token = response.get("nextPageToken")
    return files, token if isinstance(token, str) and token else None


class _DriveClient:
    """Sync Drive API wrapper; call via asyncio.to_thread from the tool."""

    def __init__(self, service: _DriveService, allowed_roots: frozenset[str]) -> None:
        self._service = service
        self._allowed_roots = allowed_roots
        self._allow_cache: dict[str, bool] = {}

    def _files(self) -> _DriveFilesResource:
        return self._service.files()

    def _get_meta(self, file_id: str, *, fields: str) -> _DriveFile:
        response = self._files().get(
            fileId=file_id,
            fields=fields,
            supportsAllDrives=True,
        ).execute()
        parsed = _file_mapping(response)
        if parsed is None:
            raise RuntimeError("Drive API returned invalid file metadata")
        return parsed

    def _is_allowed(self, file_id: str, visiting: set[str], depth: int) -> bool:
        cached = self._allow_cache.get(file_id)
        if cached is not None:
            return cached
        if file_id in self._allowed_roots:
            self._allow_cache[file_id] = True
            return True
        if file_id in visiting or depth >= _MAX_ANCESTOR_DEPTH:
            return False
        visiting.add(file_id)
        try:
            meta = self._get_meta(file_id, fields="id,parents,trashed")
            allowed = not meta.get("trashed", False) and any(
                self._is_allowed(parent, visiting, depth + 1)
                for parent in meta.get("parents", [])
            )
        except Exception:
            allowed = False
        finally:
            visiting.discard(file_id)
        self._allow_cache[file_id] = allowed
        return allowed

    @staticmethod
    def _result_item(item: _DriveFile) -> dict[str, object | None]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "mimeType": item.get("mimeType"),
            "modifiedTime": item.get("modifiedTime"),
            "size": item.get("size"),
        }

    def is_allowed(self, file_id: str) -> bool:
        return self._is_allowed(file_id, set(), 0)

    def list_folder(self, folder_id: str, *, page_size: int) -> list[dict[str, object | None]]:
        if not self.is_allowed(folder_id):
            raise PermissionError(f"Folder '{folder_id}' is outside configured Drive roots")
        query = f"'{folder_id}' in parents and trashed=false"
        response = self._files().list(
            q=query,
            pageSize=min(max(page_size, 1), 100),
            fields="files(id,name,mimeType,modifiedTime,size,parents)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            orderBy="folder,name",
        ).execute()
        files, _ = _response_files(response)
        return [self._result_item(item) for item in files]

    def list_roots(self) -> list[dict[str, object | None]]:
        roots: list[dict[str, object | None]] = []
        for root_id in sorted(self._allowed_roots):
            meta = self._get_meta(
                root_id,
                fields="id,name,mimeType,modifiedTime",
            )
            roots.append(
                {
                    "id": meta.get("id", root_id),
                    "name": meta.get("name"),
                    "mimeType": meta.get("mimeType"),
                    "modifiedTime": meta.get("modifiedTime"),
                }
            )
        return roots

    def search(self, query: str, *, page_size: int) -> list[dict[str, object | None]]:
        limit = min(max(page_size, 1), 100)
        drive_query = f"({query}) and trashed=false"
        allowed: list[dict[str, object | None]] = []
        page_token: str | None = None
        while len(allowed) < limit:
            response = self._files().list(
                q=drive_query,
                pageSize=limit,
                pageToken=page_token,
                fields="nextPageToken,files(id,name,mimeType,modifiedTime,size,parents)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            files, page_token = _response_files(response)
            for item in files:
                file_id = item.get("id", "")
                if file_id and self.is_allowed(file_id):
                    allowed.append(self._result_item(item))
                    if len(allowed) >= limit:
                        break
            if not page_token:
                break
        return allowed

    def metadata(self, file_id: str) -> dict[str, object | None]:
        if not self.is_allowed(file_id):
            raise PermissionError(f"File '{file_id}' is outside configured Drive roots")
        meta = self._get_meta(
            file_id,
            fields="id,name,mimeType,modifiedTime,size,parents,webViewLink",
        )
        return {
            "id": meta.get("id"),
            "name": meta.get("name"),
            "mimeType": meta.get("mimeType"),
            "modifiedTime": meta.get("modifiedTime"),
            "size": meta.get("size"),
            "parents": meta.get("parents"),
            "webViewLink": meta.get("webViewLink"),
        }

    def download_bytes(self, file_id: str, *, max_bytes: int) -> tuple[bytes, str, str]:
        if not self.is_allowed(file_id):
            raise PermissionError(f"File '{file_id}' is outside configured Drive roots")
        meta = self._get_meta(file_id, fields="id,name,mimeType,size")
        name = str(meta.get("name") or file_id)
        mime = str(meta.get("mimeType") or "application/octet-stream")
        raw_size = meta.get("size")
        if isinstance(raw_size, str) and raw_size.isdecimal() and int(raw_size) > max_bytes:
            raise ValueError(f"File exceeds the {max_bytes // (1024 * 1024)} MB download limit")
        export_mime = _GOOGLE_APP_EXPORT.get(mime)
        if export_mime:
            data = (
                self._files()
                .export(fileId=file_id, mimeType=export_mime)
                .execute()
            )
            if isinstance(data, str):
                content = data.encode("utf-8")
            elif isinstance(data, (bytes, bytearray)):
                content = bytes(data)
            else:
                raise RuntimeError("Drive API returned invalid exported file content")
            suggested_name = _export_filename(name, export_mime)
        else:
            data = self._files().get_media(fileId=file_id, supportsAllDrives=True).execute()
            if not isinstance(data, (bytes, bytearray)):
                raise RuntimeError("Drive API returned invalid file content")
            content = bytes(data)
            suggested_name = name
        if len(content) > max_bytes:
            raise ValueError(f"File exceeds the {max_bytes // (1024 * 1024)} MB download limit")
        return content, suggested_name, export_mime or mime


def _export_filename(name: str, export_mime: str) -> str:
    stem = Path(name).stem
    ext = mimetypes.guess_extension(export_mime) or ""
    if export_mime == "text/plain":
        ext = ".txt"
    elif export_mime == "text/csv":
        ext = ".csv"
    elif export_mime == "application/pdf" and not ext:
        ext = ".pdf"
    return f"{stem}{ext}"


def _sanitize_filename(name: str) -> str:
    cleaned = _SAFE_FILENAME.sub("_", name.strip()) or "download"
    return cleaned[:200]


def build_drive_client(config: DriveToolConfig) -> _DriveClient:
    deps = _require_google_deps()
    creds_path = _credentials_path(config)
    roots = frozenset(item.strip() for item in config.root_folder_ids if item.strip())
    if not roots:
        raise ValueError("Drive root_folder_ids must list at least one shared folder ID")
    service = build_google_service(
        deps,
        "drive",
        "v3",
        credentials_path=creds_path,
        scope=_DRIVE_READONLY_SCOPE,
        timeout=_DRIVE_HTTP_TIMEOUT_SECONDS,
    )
    return _DriveClient(cast(_DriveService, service), roots)


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "Drive action",
            enum=["list", "search", "metadata", "download"],
        ),
        folder_id=StringSchema(
            "Drive folder ID to list. Omit to describe configured root folders.",
            nullable=True,
        ),
        file_id=StringSchema(
            "Drive file ID for metadata or download.",
            nullable=True,
        ),
        query=StringSchema(
            "Drive files.list q expression (without trashed filter). Required for search.",
            nullable=True,
        ),
        path=StringSchema(
            "Optional workspace-relative path under the configured Drive download folder. "
            "Omit to use the file's Drive name.",
            nullable=True,
        ),
        page_size=IntegerSchema(
            description="Maximum items to return for list or search (default 25).",
            minimum=1,
            maximum=100,
            nullable=True,
        ),
        required=["action"],
    )
)
class GoogleDriveTool(Tool):
    """Read files from Google Drive folders shared with a service account."""

    config_key = "drive"

    @classmethod
    def config_cls(cls):
        return DriveToolConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        cfg = ctx.config.drive
        if not cfg.enabled:
            return False
        if not any(item.strip() for item in cfg.root_folder_ids):
            return False
        try:
            path = _credentials_path(cfg)
            if service_account_email_hint(path) is None:
                return False
            _require_google_deps()
        except (RuntimeError, ValueError):
            return False
        return True

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(
            workspace=Path(ctx.workspace).expanduser(),
            config=ctx.config.drive,
        )

    def __init__(
        self,
        *,
        workspace: Path,
        config: DriveToolConfig,
    ) -> None:
        self._workspace = workspace
        self._config = config
        self._client: _DriveClient | None = None

    def _get_client(self) -> _DriveClient:
        if self._client is None:
            self._client = build_drive_client(self._config)
        return self._client

    @property
    def name(self) -> str:
        return "google_drive"

    @property
    def description(self) -> str:
        return (
            "List, search, inspect, and download Google Drive files from folders shared "
            "with the configured service account. Use list/search first, then download "
            "into the workspace."
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = super().validate_params(params)
        action = params.get("action")
        if action == "search" and not str(params.get("query") or "").strip():
            errors.append("query is required when action='search'")
        if action == "metadata" and not str(params.get("file_id") or "").strip():
            errors.append("file_id is required when action='metadata'")
        if action == "download":
            if not str(params.get("file_id") or "").strip():
                errors.append("file_id is required when action='download'")
        return errors

    async def execute(
        self,
        action: str,
        folder_id: str | None = None,
        file_id: str | None = None,
        query: str | None = None,
        path: str | None = None,
        page_size: int | None = 25,
    ) -> str:
        limit = page_size if page_size is not None else 25
        try:
            client = self._get_client()
        except (RuntimeError, ValueError) as exc:
            return ToolResult.error(f"Error: {exc}")

        try:
            if action == "list":
                if folder_id and folder_id.strip():
                    items = await asyncio.to_thread(
                        client.list_folder,
                        folder_id.strip(),
                        page_size=limit,
                    )
                else:
                    items = await asyncio.to_thread(client.list_roots)
                return json.dumps({"items": items}, indent=2)
            if action == "search":
                items = await asyncio.to_thread(
                    client.search,
                    str(query or "").strip(),
                    page_size=limit,
                )
                return json.dumps({"items": items}, indent=2)
            if action == "metadata":
                meta = await asyncio.to_thread(client.metadata, str(file_id or "").strip())
                return json.dumps(meta, indent=2)
            if action == "download":
                return await self._download(client, str(file_id or "").strip(), str(path or ""))
            return ToolResult.error(f"Error: unknown action '{action}'")
        except PermissionError as exc:
            return ToolResult.error(f"Error: {exc}")
        except Exception as exc:
            return ToolResult.error(f"Error: Drive API request failed: {exc}")

    async def _download(self, client: _DriveClient, file_id: str, dest: str) -> str:
        workspace = self._workspace.resolve(strict=False)
        subdir = (self._config.download_subdir or "drive").strip() or "drive"
        destination = dest.strip()
        data, suggested_name, mime = await asyncio.to_thread(
            client.download_bytes,
            file_id,
            max_bytes=self._config.max_download_size_mb * 1024 * 1024,
        )
        if not destination:
            destination = _sanitize_filename(suggested_name)
        relative = (
            destination
            if destination.startswith(subdir + "/") or destination == subdir
            else f"{subdir}/{destination}"
        )
        try:
            target = resolve_workspace_path(
                relative,
                workspace=workspace,
                allowed_dir=workspace,
                include_media_dir=False,
            )
        except WorkspaceBoundaryError as exc:
            return ToolResult.error(f"Error: {exc}")

        if target.is_dir() or destination.endswith("/"):
            target = target / _sanitize_filename(suggested_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)
        return json.dumps(
            {
                "path": str(target.relative_to(workspace)),
                "bytes": len(data),
                "mimeType": mime,
                "name": suggested_name,
            },
            indent=2,
        )
