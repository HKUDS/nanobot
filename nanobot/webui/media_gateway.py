from __future__ import annotations

import mimetypes
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.channels.websocket.attachment_policy import IMAGE_MIME_ALLOWED, VIDEO_MIME_ALLOWED
from nanobot.config.paths import get_media_dir
from nanobot.security.workspace_access import WorkspaceScope
from nanobot.utils.media_decode import UPLOADED_FILE_TAG
from nanobot.webui.media_api import (
    serve_signed_media,
    sign_local_attachment,
    sign_media_path,
    sign_or_stage_media_path,
    signed_media_attachments,
)
from nanobot.webui.transcript import rewrite_local_markdown_images


def _default_media_dir(channel: str | None) -> Path:
    return get_media_dir(channel)


class WebUIMediaGateway:
    """Own media URL signing and WebUI markdown/media augmentation."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        logger: Any,
        media_dir: Callable[[str | None], Path] | None = None,
        secret: bytes | None = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.logger = logger
        self._media_dir: Callable[[str | None], Path] = media_dir or _default_media_dir
        self.secret = secret or secrets.token_bytes(32)

    def serve_signed_media(
        self,
        sig: str,
        payload: str,
        *,
        request: WsRequest | None = None,
        scope_for_session: Callable[[str], WorkspaceScope | None] | None = None,
    ) -> Response:
        return serve_signed_media(
            sig,
            payload,
            secret=self.secret,
            request=request,
            media_dir=self._media_dir,
            scope_for_session=scope_for_session,
        )

    def sign_or_stage_media_path(self, path: Path) -> dict[str, str] | None:
        return sign_or_stage_media_path(
            path,
            secret=self.secret,
            media_dir=self._media_dir,
            logger=self.logger,
        )

    def rewrite_local_markdown_images(
        self,
        text: str,
        *,
        workspace_path: Path | None = None,
    ) -> str:
        return rewrite_local_markdown_images(
            text,
            workspace_path=workspace_path or self.workspace_path,
            sign_path=self.sign_or_stage_media_path,
        )

    def augment_transcript_media(self, paths: list[str]) -> list[dict[str, Any]]:
        return signed_media_attachments(
            paths,
            sign_path=self.sign_or_stage_media_path,
        )

    def local_attachment_url(self, path: str, *, session_key: str) -> str:
        return sign_local_attachment(path, session_key=session_key, secret=self.secret)

    def augment_transcript_user_media(
        self, paths: list[str], local_paths: list[str], *, session_key: str,
    ) -> list[dict[str, Any]]:
        local = set(local_paths)
        media: list[dict[str, Any]] = []
        for raw in paths:
            path = Path(raw)
            stored_file = re.fullmatch(r"[0-9a-f]{12}" + re.escape(UPLOADED_FILE_TAG) + r"(.+)", path.name) if raw not in local else None
            name = stored_file.group(1) if stored_file else path.name
            mime = mimetypes.guess_type(name)[0]
            kind = "file" if stored_file else (
                "video" if mime in VIDEO_MIME_ALLOWED else "image" if mime in IMAGE_MIME_ALLOWED else "file"
            )
            try:
                if not path.is_file():
                    url = ""
                else:
                    if not path.stat().st_size:
                        kind = "file"
                    url = (self.local_attachment_url(raw, session_key=session_key) if raw in local else
                           sign_media_path(path, secret=self.secret, media_dir=self._media_dir) or "")
            except OSError:
                url = ""
            media.append({"kind": kind, "name": name, "url": url})
        return media
