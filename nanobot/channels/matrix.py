"""Matrix channel implementation for inbound sync and outbound message/media delivery."""

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any, TypeAlias

import nh3
from loguru import logger
from mistune import create_markdown
from nio import (
    AsyncClient,
    AsyncClientConfig,
    ContentRepositoryConfigError,
    DownloadError,
    InviteEvent,
    JoinError,
    MatrixRoom,
    MemoryDownloadResponse,
    RoomEncryptedMedia,
    RoomMessage,
    RoomMessageMedia,
    RoomMessageText,
    RoomSendError,
    RoomTypingError,
    SyncError,
    UploadError,
)
from nio.crypto.attachments import decrypt_attachment
from nio.exceptions import EncryptionError

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.config.loader import get_data_dir
from nanobot.utils.helpers import safe_filename

LOGGING_STACK_BASE_DEPTH = 2
# Typing state lifetime advertised to Matrix clients/servers.
TYPING_NOTICE_TIMEOUT_MS = 30_000
# Matrix typing notifications are ephemeral; spec guidance is to keep
# refreshing while work is ongoing (practically ~20-30s cadence).
# https://spec.matrix.org/v1.17/client-server-api/#typing-notifications
# Keepalive interval must stay below TYPING_NOTICE_TIMEOUT_MS so the typing
# indicator does not expire while the agent is still processing.
TYPING_KEEPALIVE_INTERVAL_SECONDS = 20.0
MATRIX_HTML_FORMAT = "org.matrix.custom.html"
MATRIX_ATTACHMENT_MARKER_TEMPLATE = "[attachment: {}]"
MATRIX_ATTACHMENT_TOO_LARGE_TEMPLATE = "[attachment: {} - too large]"
MATRIX_ATTACHMENT_FAILED_TEMPLATE = "[attachment: {} - download failed]"
MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE = "[attachment: {} - upload failed]"
MATRIX_DEFAULT_ATTACHMENT_NAME = "attachment"

# Runtime callback filter for nio event dispatch (checked via isinstance).
MATRIX_MEDIA_EVENT_FILTER = (RoomMessageMedia, RoomEncryptedMedia)
# Static typing alias for media-specific handlers/helpers.
MatrixMediaEvent: TypeAlias = RoomMessageMedia | RoomEncryptedMedia

# Markdown renderer policy:
# https://spec.matrix.org/v1.17/client-server-api/#mroommessage-msgtypes
# - Only enable portable features that map cleanly to Matrix-compatible HTML.
# - escape=True ensures raw model HTML is treated as text unless we explicitly
#   add structured support for Matrix-specific HTML features later.
MATRIX_MARKDOWN = create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "url", "superscript", "subscript"],
)

# Sanitizer policy:
# https://spec.matrix.org/v1.17/client-server-api/#mroommessage-msgtypes
# - Start from Matrix formatted-message guidance, but keep a smaller allowlist
#   to reduce risk and keep client behavior predictable for LLM output.
# - Enforce mxc:// for img src to align media rendering with Matrix content
#   repository semantics.
# - Unused spec-permitted features (e.g. some href schemes and data-mx-* attrs)
#   are intentionally deferred until explicitly needed.
MATRIX_ALLOWED_HTML_TAGS = {
    "p",
    "a",
    "strong",
    "em",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "br",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "caption",
    "sup",
    "sub",
    "img",
}
MATRIX_ALLOWED_HTML_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},
    "code": {"class"},
    "ol": {"start"},
    "img": {"src", "alt", "title", "width", "height"},
}
MATRIX_ALLOWED_URL_SCHEMES = {"https", "http", "matrix", "mailto", "mxc"}


def _filter_matrix_html_attribute(tag: str, attr: str, value: str) -> str | None:
    """Filter attribute values to a safe Matrix-compatible subset."""
    if tag == "a" and attr == "href":
        lower_value = value.lower()
        if lower_value.startswith(("https://", "http://", "matrix:", "mailto:")):
            return value
        return None

    if tag == "img" and attr == "src":
        return value if value.lower().startswith("mxc://") else None

    if tag == "code" and attr == "class":
        classes = [
            cls
            for cls in value.split()
            if cls.startswith("language-") and not cls.startswith("language-_")
        ]
        return " ".join(classes) if classes else None

    return value


MATRIX_HTML_CLEANER = nh3.Cleaner(
    tags=MATRIX_ALLOWED_HTML_TAGS,
    attributes=MATRIX_ALLOWED_HTML_ATTRIBUTES,
    attribute_filter=_filter_matrix_html_attribute,
    url_schemes=MATRIX_ALLOWED_URL_SCHEMES,
    strip_comments=True,
    link_rel="noopener noreferrer",
)


def _render_markdown_html(text: str) -> str | None:
    """Render markdown to HTML for Matrix formatted messages."""
    try:
        rendered = MATRIX_MARKDOWN(text)
        formatted = MATRIX_HTML_CLEANER.clean(rendered).strip()
    except Exception as e:
        logger.debug(
            "Matrix markdown rendering failed ({}): {}",
            type(e).__name__,
            str(e),
        )
        return None

    if not formatted:
        return None

    # Skip formatted_body for plain output (<p>...</p>) to keep payload minimal.
    stripped = formatted.strip()
    if stripped.startswith("<p>") and stripped.endswith("</p>"):
        paragraph_inner = stripped[3:-4]
        # Keep plaintext-only paragraphs minimal, but preserve inline markup/links.
        if "<" not in paragraph_inner and ">" not in paragraph_inner:
            return None

    return formatted


def _build_matrix_text_content(text: str) -> dict[str, object]:
    """Build Matrix m.text payload with plaintext fallback and optional HTML."""
    content: dict[str, object] = {
        "msgtype": "m.text",
        # Note: When `formatted_body` is present, Matrix spec expects `body` to
        # be its plaintext representation (fallback for clients without HTML).
        # We currently keep raw text (often markdown) for simplicity.
        # https://spec.matrix.org/v1.17/client-server-api/#mroommessage-msgtypes
        "body": text,
        # Matrix spec recommends always including m.mentions for message
        # semantics/interoperability, even when no mentions are present.
        # https://spec.matrix.org/v1.17/client-server-api/#mmentions
        "m.mentions": {},
    }
    formatted_html = _render_markdown_html(text)
    if not formatted_html:
        return content

    content["format"] = MATRIX_HTML_FORMAT
    content["formatted_body"] = formatted_html
    return content


class _NioLoguruHandler(logging.Handler):
    """Route stdlib logging records from matrix-nio into Loguru output."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        # Skip logging internals plus this handler frame when forwarding to Loguru.
        depth = LOGGING_STACK_BASE_DEPTH
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _configure_nio_logging_bridge() -> None:
    """Ensure matrix-nio logs are emitted through the project's Loguru format."""
    nio_logger = logging.getLogger("nio")
    if any(isinstance(handler, _NioLoguruHandler) for handler in nio_logger.handlers):
        return

    nio_logger.handlers = [_NioLoguruHandler()]
    nio_logger.propagate = False


class MatrixChannel(BaseChannel):
    """
    Matrix (Element) channel using long-polling sync.
    """

    name = "matrix"

    def __init__(
        self,
        config: Any,
        bus,
        *,
        restrict_to_workspace: bool = False,
        workspace: Path | None = None,
    ):
        """Store Matrix client settings, task handles, and outbound media policy flags."""
        super().__init__(config, bus)
        self.client: AsyncClient | None = None
        self._sync_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._restrict_to_workspace = restrict_to_workspace
        self._workspace = workspace.expanduser().resolve() if workspace else None
        self._server_upload_limit_bytes: int | None = None
        self._server_upload_limit_checked = False

    async def start(self) -> None:
        """Start Matrix client and begin sync loop."""
        self._running = True
        _configure_nio_logging_bridge()

        store_path = get_data_dir() / "matrix-store"
        store_path.mkdir(parents=True, exist_ok=True)

        self.client = AsyncClient(
            homeserver=self.config.homeserver,
            user=self.config.user_id,
            store_path=store_path,  # Where tokens are saved
            config=AsyncClientConfig(
                store_sync_tokens=True,  # Auto-persists next_batch tokens
                encryption_enabled=self.config.e2ee_enabled,
            ),
        )

        self.client.user_id = self.config.user_id
        self.client.access_token = self.config.access_token
        self.client.device_id = self.config.device_id

        self._register_event_callbacks()
        self._register_response_callbacks()

        if self.config.e2ee_enabled:
            logger.info("Matrix E2EE is enabled.")
        else:
            logger.warning(
                "Matrix E2EE is disabled; encrypted room messages may be undecryptable and "
                "encrypted-device verification is not applied on send."
            )

        if self.config.device_id:
            try:
                self.client.load_store()
            except Exception as e:
                logger.warning(
                    "Matrix store load failed ({}: {}); sync token restore is disabled and "
                    "restart may replay recent messages.",
                    type(e).__name__,
                    str(e),
                )
        else:
            logger.warning(
                "Matrix device_id is empty; sync token restore is disabled and restart may "
                "replay recent messages."
            )

        self._sync_task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """Stop the Matrix channel with graceful sync shutdown."""
        self._running = False

        for room_id in list(self._typing_tasks):
            await self._stop_typing_keepalive(room_id, clear_typing=False)

        if self.client:
            # Request sync_forever loop to exit cleanly.
            self.client.stop_sync_forever()

        if self._sync_task:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._sync_task),
                    timeout=self.config.sync_stop_grace_seconds,
                )
            except asyncio.TimeoutError:
                self._sync_task.cancel()
                try:
                    await self._sync_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        if self.client:
            await self.client.close()

    @staticmethod
    def _path_dedupe_key(path: Path) -> str:
        """Return a stable deduplication key for attachment paths."""
        expanded = path.expanduser()
        try:
            return str(expanded.resolve(strict=False))
        except OSError:
            return str(expanded)

    def _is_workspace_path_allowed(self, path: Path) -> bool:
        """Enforce optional workspace-only outbound attachment policy."""
        if not self._restrict_to_workspace:
            return True

        if self._workspace is None:
            return False

        try:
            path.resolve(strict=False).relative_to(self._workspace)
            return True
        except ValueError:
            return False

    def _collect_outbound_media_candidates(self, media: list[str]) -> list[Path]:
        """Collect unique outbound attachment paths from OutboundMessage.media."""
        candidates: list[Path] = []
        seen: set[str] = set()

        for raw in media:
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw.strip()).expanduser()
            key = self._path_dedupe_key(path)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(path)

        return candidates

    @staticmethod
    def _build_outbound_attachment_content(
        *,
        filename: str,
        mime: str,
        size_bytes: int,
        mxc_url: str,
        encryption_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build Matrix content payload for an uploaded file/image/audio/video."""
        msgtype = "m.file"
        if mime.startswith("image/"):
            msgtype = "m.image"
        elif mime.startswith("audio/"):
            msgtype = "m.audio"
        elif mime.startswith("video/"):
            msgtype = "m.video"

        content: dict[str, Any] = {
            "msgtype": msgtype,
            "body": filename,
            "filename": filename,
            "info": {
                "mimetype": mime,
                "size": size_bytes,
            },
            "m.mentions": {},
        }

        if encryption_info:
            # Encrypted media events use `file` metadata (with url/hash/key/iv),
            # while unencrypted media events use top-level `url`.
            file_info = dict(encryption_info)
            file_info["url"] = mxc_url
            content["file"] = file_info
        else:
            content["url"] = mxc_url

        return content

    def _is_encrypted_room(self, room_id: str) -> bool:
        """Return True if the Matrix room is known as encrypted."""
        if not self.client:
            return False
        room = getattr(self.client, "rooms", {}).get(room_id)
        return bool(getattr(room, "encrypted", False))

    async def _send_room_content(self, room_id: str, content: dict[str, Any]) -> None:
        """Send Matrix m.room.message content with configured E2EE send options."""
        if not self.client:
            return

        room_send_kwargs: dict[str, Any] = {
            "room_id": room_id,
            "message_type": "m.room.message",
            "content": content,
        }
        if self.config.e2ee_enabled:
            # TODO(matrix): Add explicit config for strict verified-device sending mode.
            room_send_kwargs["ignore_unverified_devices"] = True

        await self.client.room_send(**room_send_kwargs)

    async def _resolve_server_upload_limit_bytes(self) -> int | None:
        """Resolve homeserver-advertised upload limit once per channel lifecycle."""
        if self._server_upload_limit_checked:
            return self._server_upload_limit_bytes

        self._server_upload_limit_checked = True
        if not self.client:
            return None

        try:
            response = await self.client.content_repository_config()
        except Exception as e:
            logger.debug(
                "Matrix media config lookup failed ({}): {}",
                type(e).__name__,
                str(e),
            )
            return None

        upload_size = getattr(response, "upload_size", None)
        if isinstance(upload_size, int) and upload_size > 0:
            self._server_upload_limit_bytes = upload_size
            return self._server_upload_limit_bytes

        if isinstance(response, ContentRepositoryConfigError):
            logger.debug("Matrix media config lookup failed: {}", response)
            return None

        logger.debug(
            "Matrix media config lookup returned unexpected response {}",
            type(response).__name__,
        )
        return None

    async def _effective_media_limit_bytes(self) -> int:
        """
        Compute effective Matrix media size cap.

        `m.upload.size` (if advertised) is treated as the homeserver-side cap.
        `maxMediaBytes` is a local hard limit/fallback. Using the stricter value
        keeps resource usage predictable while honoring server constraints.
        """
        local_limit = max(int(self.config.max_media_bytes), 0)
        server_limit = await self._resolve_server_upload_limit_bytes()
        if server_limit is None:
            return local_limit
        if local_limit == 0:
            return 0
        return min(local_limit, server_limit)

    def _configured_media_limit_bytes(self) -> int:
        """Resolve the configured local media limit with backward compatibility."""
        for name in ("max_inbound_media_bytes", "max_media_bytes"):
            value = getattr(self.config, name, None)
            if isinstance(value, int):
                return value
        return 0

    async def _upload_and_send_attachment(
        self,
        room_id: str,
        path: Path,
        limit_bytes: int,
        relates_to: dict[str, Any] | None = None,
    ) -> str | None:
        """Upload one local file to Matrix and send it as a media message."""
        if not self.client:
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(path.name or MATRIX_DEFAULT_ATTACHMENT_NAME)

        resolved = path.expanduser().resolve(strict=False)
        filename = safe_filename(resolved.name) or MATRIX_DEFAULT_ATTACHMENT_NAME

        if not resolved.is_file():
            logger.warning("Matrix outbound attachment missing file: {}", resolved)
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(filename)

        if not self._is_workspace_path_allowed(resolved):
            logger.warning(
                "Matrix outbound attachment denied by workspace restriction: {}",
                resolved,
            )
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(filename)

        try:
            size_bytes = resolved.stat().st_size
        except OSError as e:
            logger.warning(
                "Matrix outbound attachment stat failed for {} ({}): {}",
                resolved,
                type(e).__name__,
                str(e),
            )
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(filename)

        if limit_bytes <= 0:
            logger.warning(
                "Matrix outbound attachment skipped: media limit {} blocks all uploads for {}",
                limit_bytes,
                resolved,
            )
            return MATRIX_ATTACHMENT_TOO_LARGE_TEMPLATE.format(filename)

        if size_bytes > limit_bytes:
            logger.warning(
                "Matrix outbound attachment skipped: {} bytes exceeds limit {} for {}",
                size_bytes,
                limit_bytes,
                resolved,
            )
            return MATRIX_ATTACHMENT_TOO_LARGE_TEMPLATE.format(filename)

        mime = mimetypes.guess_type(filename, strict=False)[0] or "application/octet-stream"
        encrypt_upload = self.config.e2ee_enabled and self._is_encrypted_room(room_id)
        try:
            with resolved.open("rb") as data_provider:
                upload_result = await self.client.upload(
                    data_provider,
                    content_type=mime,
                    filename=filename,
                    encrypt=encrypt_upload,
                    filesize=size_bytes,
                )
        except Exception as e:
            logger.warning(
                "Matrix outbound attachment upload failed for {} ({}): {}",
                resolved,
                type(e).__name__,
                str(e),
            )
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(filename)
        upload_response = upload_result[0] if isinstance(upload_result, tuple) else upload_result
        encryption_info: dict[str, Any] | None = None
        if isinstance(upload_result, tuple) and isinstance(upload_result[1], dict):
            encryption_info = upload_result[1]
        if isinstance(upload_response, UploadError):
            logger.warning(
                "Matrix outbound attachment upload failed for {}: {}",
                resolved,
                upload_response,
            )
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(filename)

        mxc_url = getattr(upload_response, "content_uri", None)
        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            logger.warning(
                "Matrix outbound attachment upload returned unexpected response {} for {}",
                type(upload_response).__name__,
                resolved,
            )
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(filename)

        content = self._build_outbound_attachment_content(
            filename=filename,
            mime=mime,
            size_bytes=size_bytes,
            mxc_url=mxc_url,
            encryption_info=encryption_info,
        )
        if relates_to:
            content["m.relates_to"] = relates_to
        try:
            await self._send_room_content(room_id, content)
        except Exception as e:
            logger.warning(
                "Matrix outbound attachment send failed for {} ({}): {}",
                resolved,
                type(e).__name__,
                str(e),
            )
            return MATRIX_ATTACHMENT_UPLOAD_FAILED_TEMPLATE.format(filename)
        return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send message text and optional attachments to a Matrix room, then clear typing state."""
        if not self.client:
            return

        text = msg.content or ""
        candidates = self._collect_outbound_media_candidates(msg.media)
        relates_to = self._build_thread_relates_to(msg.metadata)

        try:
            failures: list[str] = []

            if candidates:
                limit_bytes = await self._effective_media_limit_bytes()
                for path in candidates:
                    failure_marker = await self._upload_and_send_attachment(
                        room_id=msg.chat_id,
                        path=path,
                        limit_bytes=limit_bytes,
                        relates_to=relates_to,
                    )
                    if failure_marker:
                        failures.append(failure_marker)

            if failures:
                if text.strip():
                    text = f"{text.rstrip()}\n" + "\n".join(failures)
                else:
                    text = "\n".join(failures)

            if text or not candidates:
                content = _build_matrix_text_content(text)
                if relates_to:
                    content["m.relates_to"] = relates_to
                await self._send_room_content(msg.chat_id, content)
        finally:
            await self._stop_typing_keepalive(msg.chat_id, clear_typing=True)

    def _register_event_callbacks(self) -> None:
        """Register Matrix event callbacks used by this channel."""
        self.client.add_event_callback(self._on_message, RoomMessageText)
        self.client.add_event_callback(self._on_media_message, MATRIX_MEDIA_EVENT_FILTER)
        self.client.add_event_callback(self._on_room_invite, InviteEvent)

    def _register_response_callbacks(self) -> None:
        """Register response callbacks for operational error observability."""
        self.client.add_response_callback(self._on_sync_error, SyncError)
        self.client.add_response_callback(self._on_join_error, JoinError)
        self.client.add_response_callback(self._on_send_error, RoomSendError)

    @staticmethod
    def _is_auth_error(errcode: str | None) -> bool:
        """Return True if the Matrix errcode indicates auth/token problems."""
        return errcode in {"M_UNKNOWN_TOKEN", "M_FORBIDDEN", "M_UNAUTHORIZED"}

    async def _on_sync_error(self, response: SyncError) -> None:
        """Log sync errors with clear severity."""
        if self._is_auth_error(response.status_code) or response.soft_logout:
            logger.error("Matrix sync failed: {}", response)
            return
        logger.warning("Matrix sync warning: {}", response)

    async def _on_join_error(self, response: JoinError) -> None:
        """Log room-join errors from invite handling."""
        if self._is_auth_error(response.status_code):
            logger.error("Matrix join failed: {}", response)
            return
        logger.warning("Matrix join warning: {}", response)

    async def _on_send_error(self, response: RoomSendError) -> None:
        """Log message send failures."""
        if self._is_auth_error(response.status_code):
            logger.error("Matrix send failed: {}", response)
            return
        logger.warning("Matrix send warning: {}", response)

    async def _set_typing(self, room_id: str, typing: bool) -> None:
        """Best-effort typing indicator update that never blocks message flow."""
        if not self.client:
            return

        try:
            response = await self.client.room_typing(
                room_id=room_id,
                typing_state=typing,
                timeout=TYPING_NOTICE_TIMEOUT_MS,
            )
            if isinstance(response, RoomTypingError):
                logger.debug("Matrix typing update failed for room {}: {}", room_id, response)
        except Exception as e:
            logger.debug(
                "Matrix typing update failed for room {} (typing={}): {}: {}",
                room_id,
                typing,
                type(e).__name__,
                str(e),
            )

    async def _start_typing_keepalive(self, room_id: str) -> None:
        """Start periodic Matrix typing refresh for a room (spec-recommended keepalive)."""
        await self._stop_typing_keepalive(room_id, clear_typing=False)
        await self._set_typing(room_id, True)
        if not self._running:
            return

        async def _typing_loop() -> None:
            try:
                while self._running:
                    await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL_SECONDS)
                    await self._set_typing(room_id, True)
            except asyncio.CancelledError:
                pass

        self._typing_tasks[room_id] = asyncio.create_task(_typing_loop())

    async def _stop_typing_keepalive(
        self,
        room_id: str,
        *,
        clear_typing: bool,
    ) -> None:
        """Stop periodic Matrix typing refresh for a room."""
        task = self._typing_tasks.pop(room_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if clear_typing:
            await self._set_typing(room_id, False)

    async def _sync_loop(self) -> None:
        while self._running:
            try:
                # full_state applies only to the first sync inside sync_forever and helps
                # rebuild room state when restoring from stored sync tokens.
                await self.client.sync_forever(timeout=30000, full_state=True)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2)

    async def _on_room_invite(self, room: MatrixRoom, event: InviteEvent) -> None:
        allow_from = self.config.allow_from or []
        if allow_from and event.sender not in allow_from:
            return

        await self.client.join(room.room_id)

    def _is_direct_room(self, room: MatrixRoom) -> bool:
        """Return True if the room behaves like a DM (2 or fewer members)."""
        member_count = getattr(room, "member_count", None)
        return isinstance(member_count, int) and member_count <= 2

    def _is_bot_mentioned_from_mx_mentions(self, event: RoomMessage) -> bool:
        """Resolve mentions strictly from Matrix-native m.mentions payload."""
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return False

        content = source.get("content")
        if not isinstance(content, dict):
            return False

        mentions = content.get("m.mentions")
        if not isinstance(mentions, dict):
            return False

        user_ids = mentions.get("user_ids")
        if isinstance(user_ids, list) and self.config.user_id in user_ids:
            return True

        return bool(self.config.allow_room_mentions and mentions.get("room") is True)

    def _should_process_message(self, room: MatrixRoom, event: RoomMessage) -> bool:
        """Apply sender and room policy checks before processing Matrix messages."""
        if not self.is_allowed(event.sender):
            return False

        if self._is_direct_room(room):
            return True

        policy = self.config.group_policy
        if policy == "open":
            return True
        if policy == "allowlist":
            return room.room_id in (self.config.group_allow_from or [])
        if policy == "mention":
            return self._is_bot_mentioned_from_mx_mentions(event)

        return False

    def _media_dir(self) -> Path:
        """Return directory used to persist downloaded Matrix attachments."""
        media_dir = get_data_dir() / "media" / "matrix"
        media_dir.mkdir(parents=True, exist_ok=True)
        return media_dir

    @staticmethod
    def _event_source_content(event: RoomMessage) -> dict[str, Any]:
        """Extract Matrix event content payload when available."""
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return {}
        content = source.get("content")
        return content if isinstance(content, dict) else {}

    def _event_thread_root_id(self, event: RoomMessage) -> str | None:
        """Return thread root event_id if this message is inside a thread."""
        content = self._event_source_content(event)
        relates_to = content.get("m.relates_to")
        if not isinstance(relates_to, dict):
            return None
        if relates_to.get("rel_type") != "m.thread":
            return None
        root_id = relates_to.get("event_id")
        return root_id if isinstance(root_id, str) and root_id else None

    def _thread_metadata(self, event: RoomMessage) -> dict[str, str] | None:
        """Build metadata used to reply within a thread."""
        root_id = self._event_thread_root_id(event)
        if not root_id:
            return None
        reply_to = getattr(event, "event_id", None)
        meta: dict[str, str] = {"thread_root_event_id": root_id}
        if isinstance(reply_to, str) and reply_to:
            meta["thread_reply_to_event_id"] = reply_to
        return meta

    @staticmethod
    def _build_thread_relates_to(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        """Build m.relates_to payload for Matrix thread replies."""
        if not metadata:
            return None
        root_id = metadata.get("thread_root_event_id")
        if not isinstance(root_id, str) or not root_id:
            return None
        reply_to = metadata.get("thread_reply_to_event_id") or metadata.get("event_id")
        if not isinstance(reply_to, str) or not reply_to:
            return None
        return {
            "rel_type": "m.thread",
            "event_id": root_id,
            "m.in_reply_to": {"event_id": reply_to},
            "is_falling_back": True,
        }

    def _event_attachment_type(self, event: MatrixMediaEvent) -> str:
        """Map Matrix event payload/type to a stable attachment kind."""
        msgtype = self._event_source_content(event).get("msgtype")
        if msgtype == "m.image":
            return "image"
        if msgtype == "m.audio":
            return "audio"
        if msgtype == "m.video":
            return "video"
        if msgtype == "m.file":
            return "file"

        class_name = type(event).__name__.lower()
        if "image" in class_name:
            return "image"
        if "audio" in class_name:
            return "audio"
        if "video" in class_name:
            return "video"
        return "file"

    @staticmethod
    def _is_encrypted_media_event(event: MatrixMediaEvent) -> bool:
        """Return True for encrypted Matrix media events."""
        return (
            isinstance(getattr(event, "key", None), dict)
            and isinstance(getattr(event, "hashes", None), dict)
            and isinstance(getattr(event, "iv", None), str)
        )

    def _event_declared_size_bytes(self, event: MatrixMediaEvent) -> int | None:
        """Return declared media size from Matrix event info, if present."""
        info = self._event_source_content(event).get("info")
        if not isinstance(info, dict):
            return None
        size = info.get("size")
        if isinstance(size, int) and size >= 0:
            return size
        return None

    def _event_mime(self, event: MatrixMediaEvent) -> str | None:
        """Best-effort MIME extraction from Matrix media event."""
        info = self._event_source_content(event).get("info")
        if isinstance(info, dict):
            mime = info.get("mimetype")
            if isinstance(mime, str) and mime:
                return mime

        mime = getattr(event, "mimetype", None)
        if isinstance(mime, str) and mime:
            return mime
        return None

    def _event_filename(self, event: MatrixMediaEvent, attachment_type: str) -> str:
        """Build a safe filename for a Matrix attachment."""
        body = getattr(event, "body", None)
        if isinstance(body, str) and body.strip():
            candidate = safe_filename(Path(body).name)
            if candidate:
                return candidate
        return MATRIX_DEFAULT_ATTACHMENT_NAME if attachment_type == "file" else attachment_type

    def _build_attachment_path(
        self,
        event: MatrixMediaEvent,
        attachment_type: str,
        filename: str,
        mime: str | None,
    ) -> Path:
        """Compute a deterministic local file path for a downloaded attachment."""
        safe_name = safe_filename(Path(filename).name) or MATRIX_DEFAULT_ATTACHMENT_NAME
        suffix = Path(safe_name).suffix
        if not suffix and mime:
            guessed = mimetypes.guess_extension(mime, strict=False) or ""
            if guessed:
                safe_name = f"{safe_name}{guessed}"
                suffix = guessed

        stem = Path(safe_name).stem or attachment_type
        stem = stem[:72]
        suffix = suffix[:16]

        event_id = safe_filename(str(getattr(event, "event_id", "") or "evt").lstrip("$"))
        event_prefix = (event_id[:24] or "evt").strip("_")
        return self._media_dir() / f"{event_prefix}_{stem}{suffix}"

    async def _download_media_bytes(self, mxc_url: str) -> bytes | None:
        """Download media bytes from Matrix content repository."""
        if not self.client:
            return None

        response = await self.client.download(mxc=mxc_url)
        if isinstance(response, DownloadError):
            logger.warning("Matrix attachment download failed for {}: {}", mxc_url, response)
            return None

        body = getattr(response, "body", None)
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)

        if isinstance(response, MemoryDownloadResponse):
            return bytes(response.body)

        if isinstance(body, (str, Path)):
            path = Path(body)
            if path.is_file():
                try:
                    return path.read_bytes()
                except OSError as e:
                    logger.warning(
                        "Matrix attachment read failed for {} ({}): {}",
                        mxc_url,
                        type(e).__name__,
                        str(e),
                    )
                    return None

        logger.warning(
            "Matrix attachment download failed for {}: unexpected response type {}",
            mxc_url,
            type(response).__name__,
        )
        return None

    def _decrypt_media_bytes(self, event: MatrixMediaEvent, ciphertext: bytes) -> bytes | None:
        """Decrypt encrypted Matrix attachment bytes."""
        key_obj = getattr(event, "key", None)
        hashes = getattr(event, "hashes", None)
        iv = getattr(event, "iv", None)

        key = key_obj.get("k") if isinstance(key_obj, dict) else None
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        if not isinstance(key, str) or not isinstance(sha256, str) or not isinstance(iv, str):
            logger.warning(
                "Matrix encrypted attachment missing key material for event {}",
                getattr(event, "event_id", ""),
            )
            return None

        try:
            return decrypt_attachment(ciphertext, key, sha256, iv)
        except (EncryptionError, ValueError, TypeError) as e:
            logger.warning(
                "Matrix encrypted attachment decryption failed for event {} ({}): {}",
                getattr(event, "event_id", ""),
                type(e).__name__,
                str(e),
            )
            return None

    async def _fetch_media_attachment(
        self,
        room: MatrixRoom,
        event: MatrixMediaEvent,
    ) -> tuple[dict[str, Any] | None, str]:
        """Download and prepare a Matrix attachment for inbound processing."""
        attachment_type = self._event_attachment_type(event)
        mime = self._event_mime(event)
        filename = self._event_filename(event, attachment_type)
        mxc_url = getattr(event, "url", None)

        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            logger.warning(
                "Matrix attachment skipped in room {}: invalid mxc URL {}",
                room.room_id,
                mxc_url,
            )
            return None, MATRIX_ATTACHMENT_FAILED_TEMPLATE.format(filename)

        limit_bytes = await self._effective_media_limit_bytes()
        declared_size = self._event_declared_size_bytes(event)
        if (
            declared_size is not None
            and declared_size > limit_bytes
        ):
            logger.warning(
                "Matrix attachment skipped in room {}: declared size {} exceeds limit {}",
                room.room_id,
                declared_size,
                limit_bytes,
            )
            return None, MATRIX_ATTACHMENT_TOO_LARGE_TEMPLATE.format(filename)

        downloaded = await self._download_media_bytes(mxc_url)
        if downloaded is None:
            return None, MATRIX_ATTACHMENT_FAILED_TEMPLATE.format(filename)

        encrypted = self._is_encrypted_media_event(event)
        data = downloaded
        if encrypted:
            decrypted = self._decrypt_media_bytes(event, downloaded)
            if decrypted is None:
                return None, MATRIX_ATTACHMENT_FAILED_TEMPLATE.format(filename)
            data = decrypted

        if len(data) > limit_bytes:
            logger.warning(
                "Matrix attachment skipped in room {}: downloaded size {} exceeds limit {}",
                room.room_id,
                len(data),
                limit_bytes,
            )
            return None, MATRIX_ATTACHMENT_TOO_LARGE_TEMPLATE.format(filename)

        path = self._build_attachment_path(
            event,
            attachment_type,
            filename,
            mime,
        )
        try:
            path.write_bytes(data)
        except OSError as e:
            logger.warning(
                "Matrix attachment persist failed for room {} ({}): {}",
                room.room_id,
                type(e).__name__,
                str(e),
            )
            return None, MATRIX_ATTACHMENT_FAILED_TEMPLATE.format(filename)

        attachment = {
            "type": attachment_type,
            "mime": mime,
            "filename": filename,
            "event_id": str(getattr(event, "event_id", "") or ""),
            "encrypted": encrypted,
            "size_bytes": len(data),
            "path": str(path),
            "mxc_url": mxc_url,
        }
        return attachment, MATRIX_ATTACHMENT_MARKER_TEMPLATE.format(path)

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        # Ignore self messages
        if event.sender == self.config.user_id:
            return

        if not self._should_process_message(room, event):
            return

        await self._start_typing_keepalive(room.room_id)
        try:
            metadata: dict[str, Any] = {
                "room": getattr(room, "display_name", room.room_id),
            }
            event_id = getattr(event, "event_id", None)
            if isinstance(event_id, str) and event_id:
                metadata["event_id"] = event_id
            thread_meta = self._thread_metadata(event)
            if thread_meta:
                metadata.update(thread_meta)
            await self._handle_message(
                sender_id=event.sender,
                chat_id=room.room_id,
                content=event.body,
                metadata=metadata,
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise

    async def _on_media_message(self, room: MatrixRoom, event: MatrixMediaEvent) -> None:
        """Handle inbound Matrix media events and forward local attachment paths."""
        if event.sender == self.config.user_id:
            return

        if not self._should_process_message(room, event):
            return

        attachment, marker = await self._fetch_media_attachment(room, event)
        attachments = [attachment] if attachment else []
        markers = [marker]
        media_paths = [a["path"] for a in attachments]

        body = getattr(event, "body", None)
        content_parts: list[str] = []
        if isinstance(body, str) and body.strip():
            content_parts.append(body.strip())
        content_parts.extend(markers)

        # TODO: Optionally add audio transcription support for Matrix attachments,
        # behind explicit config.

        await self._start_typing_keepalive(room.room_id)
        try:
            metadata: dict[str, Any] = {
                "room": getattr(room, "display_name", room.room_id),
                "attachments": attachments,
            }
            event_id = getattr(event, "event_id", None)
            if isinstance(event_id, str) and event_id:
                metadata["event_id"] = event_id
            thread_meta = self._thread_metadata(event)
            if thread_meta:
                metadata.update(thread_meta)
            await self._handle_message(
                sender_id=event.sender,
                chat_id=room.room_id,
                content="\n".join(content_parts),
                media=media_paths,
                metadata=metadata,
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise
