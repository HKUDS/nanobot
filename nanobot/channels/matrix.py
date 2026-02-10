import asyncio
import logging
from typing import Any

from loguru import logger
from mistune import create_markdown
from nio import (
    AsyncClient,
    AsyncClientConfig,
    InviteEvent,
    JoinError,
    MatrixRoom,
    RoomMessageText,
    RoomSendError,
    RoomTypingError,
    SyncError,
)

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.config.loader import get_data_dir

LOGGING_STACK_BASE_DEPTH = 2
TYPING_NOTICE_TIMEOUT_MS = 30_000
MATRIX_HTML_FORMAT = "org.matrix.custom.html"

# Keep plugin output aligned with Matrix recommended HTML tags:
# https://spec.matrix.org/latest/client-server-api/#mroommessage-msgtypes
# - table/strikethrough/task_lists are already used in replies.
# - url, superscript, and subscript map to common tags (<a>, <sup>, <sub>)
#   that Matrix clients (e.g. Element/FluffyChat) can render consistently.
# We intentionally avoid plugins that emit less-portable tags to keep output
# predictable across clients.
MATRIX_MARKDOWN = create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "task_lists", "url", "superscript", "subscript"],
)


def _render_markdown_html(text: str) -> str | None:
    """Render markdown to HTML for Matrix formatted messages."""
    try:
        formatted = MATRIX_MARKDOWN(text).strip()
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


def _build_matrix_text_content(text: str) -> dict[str, str]:
    """Build Matrix m.text payload with plaintext fallback and optional HTML."""
    content: dict[str, str] = {"msgtype": "m.text", "body": text}
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

    def __init__(self, config: Any, bus):
        super().__init__(config, bus)
        self.client: AsyncClient | None = None
        self._sync_task: asyncio.Task | None = None

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
                encryption_enabled=True,
            ),
        )

        self.client.user_id = self.config.user_id
        self.client.access_token = self.config.access_token
        self.client.device_id = self.config.device_id

        self._register_event_callbacks()
        self._register_response_callbacks()

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

    async def send(self, msg: OutboundMessage) -> None:
        if not self.client:
            return

        try:
            await self.client.room_send(
                room_id=msg.chat_id,
                message_type="m.room.message",
                content=_build_matrix_text_content(msg.content),
                ignore_unverified_devices=True,
            )
        finally:
            await self._set_typing(msg.chat_id, False)

    def _register_event_callbacks(self) -> None:
        """Register Matrix event callbacks used by this channel."""
        self.client.add_event_callback(self._on_message, RoomMessageText)
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

    def _is_bot_mentioned_from_mx_mentions(self, event: RoomMessageText) -> bool:
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

    def _should_process_message(self, room: MatrixRoom, event: RoomMessageText) -> bool:
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

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        # Ignore self messages
        if event.sender == self.config.user_id:
            return

        if not self._should_process_message(room, event):
            return

        await self._set_typing(room.room_id, True)
        try:
            await self._handle_message(
                sender_id=event.sender,
                chat_id=room.room_id,
                content=event.body,
                metadata={"room": getattr(room, "display_name", room.room_id)},
            )
        except Exception:
            await self._set_typing(room.room_id, False)
            raise
