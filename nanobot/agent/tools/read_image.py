"""Read image tool: lets the agent view an image file on disk."""

import base64
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.utils.helpers import detect_image_mime


class ReadImageTool(Tool):
    """Read an image file and return it as a multimodal content block."""

    _MAX_BYTES = 20 * 1024 * 1024  # 20 MB
    _SUPPORTED_MIME_TYPES = {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    def _resolve(self, path: str) -> Path:
        from nanobot.agent.tools.filesystem import _resolve_path
        return _resolve_path(path, self._workspace, self._allowed_dir)

    @property
    def name(self) -> str:
        return "read_image"

    @property
    def description(self) -> str:
        return (
            "Read an image file and display it for visual analysis. "
            "Supports JPEG, PNG, GIF, and WebP. Use this when you need to "
            "see or describe an image on disk."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the image file (absolute or relative to workspace)",
                },
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str | list[dict[str, Any]]:
        path_str = kwargs["path"]
        try:
            resolved = self._resolve(path_str)
        except PermissionError as e:
            return f"Error: {e}"

        if not resolved.is_file():
            return f"Error: file not found: {path_str}"

        try:
            size_bytes = resolved.stat().st_size
        except OSError as e:
            return f"Error: could not access image file: {e}"

        if size_bytes > self._MAX_BYTES:
            return f"Error: image too large ({size_bytes / 1024 / 1024:.1f} MB, max 20 MB)"

        try:
            raw = resolved.read_bytes()
        except OSError as e:
            return f"Error: could not read image file: {e}"

        mime = detect_image_mime(raw)
        if mime not in self._SUPPORTED_MIME_TYPES:
            return f"Error: not a recognized image file ({resolved.suffix})"

        b64 = base64.b64encode(raw).decode()
        return [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": f"[Image: {resolved.name}, {len(raw) / 1024:.0f} KB, {mime}]"},
        ]
