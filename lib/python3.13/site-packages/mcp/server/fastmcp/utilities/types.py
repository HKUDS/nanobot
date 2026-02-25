"""Common types used across FastMCP."""

import base64
from pathlib import Path

from mcp.types import AudioContent, ImageContent


class Image:
    """Helper class for returning images from tools."""

    def __init__(
        self,
        path: str | Path | None = None,
        data: bytes | None = None,
        format: str | None = None,
    ):
        if path is None and data is None:  # pragma: no cover
            raise ValueError("Either path or data must be provided")
        if path is not None and data is not None:  # pragma: no cover
            raise ValueError("Only one of path or data can be provided")

        self.path = Path(path) if path else None
        self.data = data
        self._format = format
        self._mime_type = self._get_mime_type()

    def _get_mime_type(self) -> str:
        """Get MIME type from format or guess from file extension."""
        if self._format:  # pragma: no cover
            return f"image/{self._format.lower()}"

        if self.path:
            suffix = self.path.suffix.lower()
            return {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(suffix, "application/octet-stream")
        return "image/png"  # pragma: no cover  # default for raw binary data

    def to_image_content(self) -> ImageContent:
        """Convert to MCP ImageContent."""
        if self.path:
            with open(self.path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
        elif self.data is not None:  # pragma: no cover
            data = base64.b64encode(self.data).decode()
        else:  # pragma: no cover
            raise ValueError("No image data available")

        return ImageContent(type="image", data=data, mimeType=self._mime_type)


class Audio:
    """Helper class for returning audio from tools."""

    def __init__(
        self,
        path: str | Path | None = None,
        data: bytes | None = None,
        format: str | None = None,
    ):
        if not bool(path) ^ bool(data):  # pragma: no cover
            raise ValueError("Either path or data can be provided")

        self.path = Path(path) if path else None
        self.data = data
        self._format = format
        self._mime_type = self._get_mime_type()

    def _get_mime_type(self) -> str:
        """Get MIME type from format or guess from file extension."""
        if self._format:  # pragma: no cover
            return f"audio/{self._format.lower()}"

        if self.path:
            suffix = self.path.suffix.lower()
            return {
                ".wav": "audio/wav",
                ".mp3": "audio/mpeg",
                ".ogg": "audio/ogg",
                ".flac": "audio/flac",
                ".aac": "audio/aac",
                ".m4a": "audio/mp4",
            }.get(suffix, "application/octet-stream")
        return "audio/wav"  # pragma: no cover  # default for raw binary data

    def to_audio_content(self) -> AudioContent:
        """Convert to MCP AudioContent."""
        if self.path:
            with open(self.path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
        elif self.data is not None:  # pragma: no cover
            data = base64.b64encode(self.data).decode()
        else:  # pragma: no cover
            raise ValueError("No audio data available")

        return AudioContent(type="audio", data=data, mimeType=self._mime_type)
