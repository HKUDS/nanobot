"""Workspace-scoped source preview payloads for the WebUI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from nanobot.config.paths import get_media_dir
from nanobot.security.workspace_access import WorkspaceScope
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path
from nanobot.webui.path_evidence import resolve_with_evidence

MAX_FILE_PREVIEW_BYTES = 384 * 1024


class WebUIFilePreviewError(ValueError):
    """Raised when a file cannot be previewed through the WebUI."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def file_preview_payload(
    raw_path: str | None,
    *,
    scope: WorkspaceScope,
    evidence_provider: Callable[[], list[Path]] | None = None,
    max_bytes: int = MAX_FILE_PREVIEW_BYTES,
) -> dict[str, Any]:
    """Return a text preview for a file allowed by the session workspace scope."""

    resolved = _resolve_preview_path(raw_path, scope=scope, evidence_provider=evidence_provider)

    try:
        with open(resolved, "rb") as f:
            raw = f.read(max_bytes + 1)
    except OSError as e:
        raise WebUIFilePreviewError(500, "failed to read file") from e

    if b"\0" in raw[:4096]:
        raise WebUIFilePreviewError(415, "binary files cannot be previewed")

    truncated = len(raw) > max_bytes
    preview_bytes = raw[:max_bytes]
    try:
        content = preview_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = preview_bytes.decode("utf-8", errors="replace")

    display_path = _display_path(resolved, scope.project_path)
    return {
        "path": str(resolved),
        "display_path": display_path,
        "project_path": str(scope.project_path),
        "language": _language_for_path(resolved),
        "content": content,
        "size": resolved.stat().st_size,
        "truncated": truncated,
    }


def file_preview_availability_payload(
    raw_path: str | None,
    *,
    scope: WorkspaceScope,
    evidence_provider: Callable[[], list[Path]] | None = None,
) -> dict[str, bool]:
    """Confirm that a path is a readable text preview candidate without loading it fully."""

    resolved = _resolve_preview_path(raw_path, scope=scope, evidence_provider=evidence_provider)
    try:
        with open(resolved, "rb") as f:
            prefix = f.read(4096)
    except OSError as e:
        raise WebUIFilePreviewError(500, "failed to read file") from e
    if b"\0" in prefix:
        raise WebUIFilePreviewError(415, "binary files cannot be previewed")
    return {"available": True}


def _resolve_preview_path(
    raw_path: str | None,
    *,
    scope: WorkspaceScope,
    evidence_provider: Callable[[], list[Path]] | None = None,
) -> Path:
    path = _clean_preview_path(raw_path)
    if not path:
        raise WebUIFilePreviewError(400, "missing path")
    if len(path) > 4096:
        raise WebUIFilePreviewError(400, "path is too long")

    def _resolve(candidate: str) -> Path:
        extra_roots = [get_media_dir()] if scope.restrict_to_workspace else None
        return resolve_allowed_path(
            candidate,
            workspace=scope.project_path,
            allowed_root=scope.project_path if scope.restrict_to_workspace else None,
            extra_allowed_roots=extra_roots,
            strict=True,
        )

    def _resolve_retry(candidate: str) -> Path:
        try:
            return _resolve(candidate)
        except FileNotFoundError as e:
            raise WebUIFilePreviewError(404, "file not found") from e
        except WorkspaceBoundaryError as e:
            raise WebUIFilePreviewError(403, "file is outside the current workspace") from e
        except OSError as e:
            raise WebUIFilePreviewError(400, "invalid path") from e

    def _fallback_evidence() -> Path:
        """Try session tool-activity evidence dirs when the project-root base misses."""
        evidence_dirs = evidence_provider() if evidence_provider is not None else None
        if not evidence_dirs:
            raise WebUIFilePreviewError(404, "file not found")
        resolved = resolve_with_evidence(path, evidence_dirs, scope=scope)
        if resolved is None:
            raise WebUIFilePreviewError(404, "file not found")
        return resolved

    try:
        resolved = _resolve(path)
    except FileNotFoundError:
        # Tolerate references that repeat the project directory name as a
        # prefix (e.g. "qizicheng-skill管理删除优化/01_docs/..." when the
        # session project_path is ".../qizicheng-skill管理删除优化"): strip
        # one leading "<project name>/" and retry once.  First-resolution
        # behavior for normal relative/absolute paths is unchanged.
        project_name = scope.project_path.name
        project_prefix = f"{project_name}/"
        if project_name and path.startswith(project_prefix):
            try:
                resolved = _resolve_retry(path[len(project_prefix):])
            except WebUIFilePreviewError:
                resolved = _fallback_evidence()
        else:
            resolved = _fallback_evidence()
    except WorkspaceBoundaryError as e:
        raise WebUIFilePreviewError(403, "file is outside the current workspace") from e
    except OSError as e:
        raise WebUIFilePreviewError(400, "invalid path") from e

    if not resolved.is_file():
        raise WebUIFilePreviewError(404, "file not found")
    return resolved


def _clean_preview_path(raw_path: str | None) -> str:
    if raw_path is None:
        return ""
    value = raw_path.strip()
    if not value:
        return ""
    if value.startswith("file://"):
        parsed = urlparse(value)
        value = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:[\\/]", value):
            value = value[1:]
    else:
        value = unquote(value)
    value = value.split("?", 1)[0].split("#", 1)[0].strip()
    if not re.match(r"^[A-Za-z]:[\\/]", value):
        value = re.sub(r":\d+(?::\d+)?$", "", value)
    return value


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _language_for_path(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower().lstrip(".")
    if name == "dockerfile":
        return "dockerfile"
    return {
        "cjs": "javascript",
        "css": "css",
        "cts": "typescript",
        "html": "html",
        "js": "javascript",
        "json": "json",
        "jsonl": "json",
        "jsx": "jsx",
        "md": "markdown",
        "mdx": "markdown",
        "mjs": "javascript",
        "mts": "typescript",
        "py": "python",
        "pyi": "python",
        "scss": "scss",
        "sh": "bash",
        "toml": "toml",
        "ts": "typescript",
        "tsx": "tsx",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(ext, ext or "text")
