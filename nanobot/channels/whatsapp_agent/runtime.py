"""WhatsApp Agent Platform channel.

Connects a personal agent to its creator's WhatsApp account through the
official Agent Platform REST API (``https://api.whatsapp.com/agent/v1``).

This is a different product from the ``whatsapp`` channel, which links a
WhatsApp device with Neonize:

* Authentication is an opaque per-agent API token, not a device session.
* Updates arrive by long-polling ``GET /updates``, not by a client connection.
* The agent can only ever talk to its creator, and cannot join groups.
* Conversations are not end-to-end encrypted.

Because the API exposes a single long-poll stream and a small per-method rate
budget, delivery is deliberately serial: one poll at a time, one reply at a
time, and progress/typing traffic is kept off by default.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import time
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.whatsapp_agent.protocol import (
    ACCEPTED_UPLOAD_MIME,
    API_BASE,
    RATE_LIMITS,
    TEXT_MAX_CHARS,
    USER_AGENT,
    APIError,
    InboundMedia,
    PollBatch,
    WhatsAppAgentAPIError,
    WhatsAppAgentAuthError,
    classify_error,
    media_limit_for,
    normalize_mime,
    outbound_kind_for_mime,
    parse_poll_batch,
    quote_safe_url,
)
from nanobot.channels.whatsapp_agent.protocol import (
    InboundMessage as PlatformMessage,
)
from nanobot.channels.whatsapp_agent.state import (
    WhatsAppAgentState,
    default_state_dir,
    token_fingerprint,
)
from nanobot.config.schema import Base
from nanobot.events import ContextCompactionEvent
from nanobot.utils.helpers import safe_filename, split_message

# The API allows at most one in-flight poll per agent and counts every request
# over a rolling 60-second window, so the channel paces itself below each cap.
_RATE_LIMIT_MARGIN = 1
_RATE_WINDOW_SECONDS = 60.0
# 15 polls/minute is one per 4s even when traffic is continuous.
_MIN_POLL_GAP_SECONDS = 4.1

_MAX_POLL_LIMIT = 100
_DEFAULT_POLL_LIMIT = 50
# The typing indicator expires after 25s, so refresh inside that window.
_TYPING_REFRESH_SECONDS = 20.0

_BACKOFF_MAX_SECONDS = 60.0
_POLL_REPLACED_SLEEP_SECONDS = 10.0
# After a non-retryable 4xx the request will never succeed unchanged.
_BAD_REQUEST_SLEEP_SECONDS = 60.0

# Local conversation key. The platform allows exactly one counterparty — the
# agent's creator — so a stable key survives the identifier changing.
CREATOR_CHAT_ID = "creator"

AUTH_FAILURE_MESSAGE = (
    "WhatsApp Agent API token was rejected. Regenerate it in WhatsApp → "
    "Settings → Agents → the agent's chat → Chat info → API key, then update "
    "channels.whatsapp_agent.token."
)

# Placeholders for media-only messages, matching other nanobot channels.
_MEDIA_PLACEHOLDERS = {
    "image": "[image]",
    "video": "[video]",
    "sticker": "[sticker]",
    "audio": "[voice note]",
    "document": "[document]",
}


class WhatsAppAgentConfig(Base):
    """WhatsApp Agent Platform channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    state_dir: str = ""
    poll_timeout: int = Field(default=25, ge=0, le=25)
    mark_read: bool = True
    typing_indicator: bool = True
    download_media: bool = True
    delete_media_after_download: bool = False
    max_media_mb: int = Field(default=16, ge=1, le=16)
    retry_ambiguous_sends: bool = False
    # Progress/tool-hint chatter spends the 12 sends/minute budget, so it stays
    # off unless an operator opts in.
    send_progress: bool = False
    send_tool_hints: bool = False


class _RollingWindowLimiter:
    """Pace requests per method over a rolling 60-second window.

    The API counts each method separately, so a burst of sends cannot borrow
    budget from the poll counter. Waiting here keeps the channel under the cap
    without depending on the server to reject it.
    """

    def __init__(self, limits: dict[str, int], margin: int) -> None:
        self._limits = {
            method: max(limit - margin, 1) for method, limit in limits.items()
        }
        self._events: dict[str, deque[float]] = {}

    async def acquire(self, method: str) -> None:
        limit = self._limits.get(method, 1)
        while True:
            now = time.monotonic()
            events = self._events.setdefault(method, deque())
            while events and now - events[0] >= _RATE_WINDOW_SECONDS:
                events.popleft()
            if len(events) < limit:
                events.append(now)
                return
            await asyncio.sleep(_RATE_WINDOW_SECONDS - (now - events[0]) + 0.05)


class WhatsAppAgentChannel(BaseChannel):
    """WhatsApp Agent Platform channel using the official agent API."""

    name = "whatsapp_agent"
    display_name = "WhatsApp Agent Platform"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WhatsAppAgentConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WhatsAppAgentConfig.model_validate(config)
        super().__init__(config, bus)
        self._client: httpx.AsyncClient | None = None
        self._limiter = _RollingWindowLimiter(RATE_LIMITS, _RATE_LIMIT_MARGIN)
        self._state = WhatsAppAgentState()
        self._typing_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------

    def progress_transport_defaults(self) -> tuple[bool, bool]:
        """Keep progress traffic opt-in; each hint spends the send budget."""
        return self.config.send_progress, self.config.send_tool_hints

    def should_retry_send_error(self, error: Exception) -> bool:
        """Return whether the channel manager may retry a failed delivery.

        A retry is only safe when the first attempt provably did not deliver:
        rate limits and ``503``/``131016`` are confirmed non-delivery. A ``500``
        or a read timeout leaves the outcome unknown, so it is not retried
        unless the operator explicitly accepts possible duplicates.
        """
        if isinstance(error, WhatsAppAgentAuthError):
            return False
        if isinstance(error, WhatsAppAgentAPIError):
            api_error = error.error
            if api_error.retryable:
                return True
            if api_error.ambiguous:
                return bool(self.config.retry_ambiguous_sends)
            # Any other 4xx fails identically until the request or token changes.
            return False
        if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
            # The request never reached the API, so resending cannot duplicate.
            return True
        if isinstance(error, httpx.HTTPError):
            # Read timeout or protocol failure after the request was written.
            return bool(self.config.retry_ambiguous_sends)
        return True

    def start_error_message(self, error: Exception) -> str | None:
        if isinstance(error, WhatsAppAgentAuthError):
            return AUTH_FAILURE_MESSAGE
        return None

    def _new_http_client(self) -> httpx.AsyncClient:
        """Create the client shared by polling, statuses, and media calls.

        The read timeout is deliberately well above the long-poll window so an
        ordinary send delay never turns into an unresolved delivery state.
        """
        read_timeout = max(self.config.poll_timeout + 15.0, 40.0)
        return httpx.AsyncClient(
            timeout=httpx.Timeout(read_timeout, connect=15.0),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": USER_AGENT},
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        method_key: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        """Perform one paced API request and decode a JSON body when present."""
        client = self._client
        if client is None:
            raise RuntimeError("WhatsApp Agent Platform channel is not connected")

        await self._limiter.acquire(method_key)
        response = await client.request(
            method,
            f"{API_BASE}{path}",
            params=params,
            json=json_body,
            files=files,
            data=data,
            headers=self._auth_headers(),
        )
        if response.status_code == 204:
            return 204, None
        payload: Any = None
        if response.content:
            with suppress(ValueError):
                payload = response.json()
        return response.status_code, payload

    async def _request_ok(
        self,
        method: str,
        path: str,
        *,
        method_key: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a request that must succeed, raising a classified error."""
        status_code, payload = await self._request(
            method,
            path,
            method_key=method_key,
            params=params,
            json_body=json_body,
            files=files,
            data=data,
        )
        if 200 <= status_code < 300:
            return payload
        error = classify_error(
            status_code, payload, media_endpoint=method_key == "media"
        )
        if error.invalid_token:
            raise WhatsAppAgentAuthError(str(error))
        raise WhatsAppAgentAPIError(error)

    # ------------------------------------------------------------------
    # Durable state
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        configured = self.config.state_dir.strip()
        base = Path(configured).expanduser() if configured else default_state_dir()
        return base / "state.json"

    def _load_state(self) -> None:
        """Load the cursor, resetting it when the token identifies a new agent."""
        path = self._state_path()
        self._state = WhatsAppAgentState.load(path)
        if self._state.reset_for_token(self.config.token):
            self.logger.info("WhatsApp Agent token changed; restarting the poll cursor")

    def _persist(self) -> None:
        """Persist the cursor before it is trusted.

        A lost cursor replays a batch (deduplicated by wamid); a cursor written
        before the batch is handled would drop messages. The write is therefore
        ordered after each message is recorded and fsynced by ``state.save``.
        """
        try:
            self._state.save(self._state_path())
        except OSError:
            self.logger.exception("Failed to persist WhatsApp Agent poll state")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.config.token.strip():
            raise WhatsAppAgentAuthError(
                "WhatsApp Agent Platform requires a token. Create an agent in "
                "WhatsApp → Settings → Agents, then copy its API key."
            )

        self._load_state()
        self._client = self._new_http_client()
        self._running = True
        backoff = 1.0
        loop = asyncio.get_running_loop()
        self.logger.info(
            "Starting WhatsApp Agent Platform channel (long-poll, timeout={}s)",
            self.config.poll_timeout,
        )

        try:
            last_poll = 0.0
            while self._running:
                gap = loop.time() - last_poll
                if gap < _MIN_POLL_GAP_SECONDS:
                    await asyncio.sleep(_MIN_POLL_GAP_SECONDS - gap)
                last_poll = loop.time()
                try:
                    batch = await self._poll_once()
                    backoff = 1.0
                    if batch is not None:
                        await self._process_batch(batch)
                except asyncio.CancelledError:
                    raise
                except WhatsAppAgentAuthError:
                    # An invalid token cannot recover by retrying; surface it.
                    self._running = False
                    raise
                except WhatsAppAgentAPIError as exc:
                    backoff, last_poll = await self._handle_api_error(
                        exc.error, backoff, last_poll
                    )
                except httpx.HTTPError as exc:
                    self.logger.warning("WhatsApp Agent poll transport error: {}", exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX_SECONDS)
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False
            await self._stop_typing()
            await self._close_client()

    async def _handle_api_error(
        self,
        error: APIError,
        backoff: float,
        last_poll: float,
    ) -> tuple[float, float]:
        """Apply the documented recovery for a failed poll."""
        if error.poll_replaced:
            self.logger.error(
                "Another poller replaced this WhatsApp Agent poll (409). "
                "Run a single gateway instance per agent token. {}",
                error,
            )
            await asyncio.sleep(_POLL_REPLACED_SLEEP_SECONDS)
            return backoff, last_poll
        if error.rate_limited or error.status_code >= 500:
            self.logger.warning("WhatsApp Agent poll failed; backing off: {}", error)
            await asyncio.sleep(backoff)
            return min(backoff * 2, _BACKOFF_MAX_SECONDS), last_poll
        self.logger.error("WhatsApp Agent poll rejected: {}", error)
        await asyncio.sleep(_BAD_REQUEST_SLEEP_SECONDS)
        return backoff, last_poll

    async def stop(self) -> None:
        self._running = False
        await self._stop_typing()
        await self._close_client()
        self._persist()

    async def _close_client(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_once(self) -> PollBatch | None:
        """Run one long poll. Returns None when the timeout elapsed empty."""
        params: dict[str, Any] = {
            "limit": _DEFAULT_POLL_LIMIT,
            "timeout": self.config.poll_timeout,
        }
        if self._state.initialized and self._state.offset is not None:
            # next_offset is a signed 64-bit integer passed back unchanged.
            params["offset"] = self._state.offset

        status_code, payload = await self._request(
            "GET", "/updates", method_key="updates", params=params
        )
        if status_code == 204:
            # No body and no next_offset: the next poll reuses the same cursor.
            return None
        if status_code != 200:
            error = classify_error(status_code, payload)
            if error.invalid_token:
                raise WhatsAppAgentAuthError(str(error))
            raise WhatsAppAgentAPIError(error)
        return parse_poll_batch(payload)

    async def _process_batch(self, batch: PollBatch) -> None:
        """Handle one batch in order, persisting progress as it goes."""
        for receipt in batch.statuses:
            self._state.note_status(receipt.wamid, receipt.status)

        for message in batch.messages:
            if self._state.has_message(message.wamid):
                continue
            # Record before handling: a crash after this point re-reads the
            # batch but never answers the same message twice.
            self._state.note_message(message.wamid)
            self._persist()
            try:
                await self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception(
                    "Failed to handle WhatsApp Agent message {}", message.wamid
                )

        if batch.next_offset is not None:
            self._state.accept_offset(batch.next_offset)
        self._persist()

    # ------------------------------------------------------------------
    # Inbound handling
    # ------------------------------------------------------------------

    async def _dispatch(self, message: PlatformMessage) -> None:
        """Route one inbound message into the agent pipeline."""
        if message.kind == "reaction":
            # Reactions are receive-only on this platform and carry no reply.
            self.logger.debug(
                "Ignoring reaction from {} to {}", message.sender, message.reaction_to
            )
            return
        if not message.is_user_authored:
            # A quoted agent message or an echo of our own send.
            return
        if message.kind == "unknown":
            self.logger.warning("Ignoring unsupported WhatsApp Agent message type")
            return

        # Prefer the freshest inbound identifier: it is the only value the API
        # accepts in ``to``, and it may change if the creator re-registers.
        self._state.note_creator(message.sender)

        if self.config.mark_read or self.config.typing_indicator:
            await self._acknowledge(message.wamid)

        media_paths, content = await self._materialize(message)

        await self._handle_message(
            sender_id=message.sender,
            chat_id=CREATOR_CHAT_ID,
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.wamid,
                "origin_message_id": message.wamid,
                "wa_id": message.sender,
            },
            is_dm=True,
        )

    async def _acknowledge(self, wamid: str) -> None:
        """Mark read and start the typing indicator, best effort."""
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": wamid,
        }
        if self.config.typing_indicator:
            # ``type`` is required inside the object and only accepts "text".
            body["typing_indicator"] = {"type": "text"}
        try:
            await self._request_ok(
                "POST", "/statuses", method_key="statuses", json_body=body
            )
        except WhatsAppAgentAuthError:
            raise
        except Exception as exc:
            # A read receipt is an affordance, never a processing gate.
            self.logger.debug("Read/typing receipt failed for {}: {}", wamid, exc)
            return
        if self.config.typing_indicator:
            self._start_typing(wamid)

    def _start_typing(self, wamid: str) -> None:
        """Refresh the typing indicator while the turn is running."""
        self._cancel_typing_task()

        async def _refresh() -> None:
            try:
                while True:
                    await asyncio.sleep(_TYPING_REFRESH_SECONDS)
                    await self._request(
                        "POST",
                        "/statuses",
                        method_key="statuses",
                        json_body={
                            "messaging_product": "whatsapp",
                            "status": "read",
                            "message_id": wamid,
                            "typing_indicator": {"type": "text"},
                        },
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.debug("Typing refresh stopped for {}: {}", wamid, exc)

        self._typing_task = asyncio.create_task(_refresh(), name="whatsapp-agent-typing")

    def _cancel_typing_task(self) -> None:
        task = self._typing_task
        self._typing_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _stop_typing(self) -> None:
        task = self._typing_task
        self._typing_task = None
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _materialize(self, message: PlatformMessage) -> tuple[list[str], str]:
        """Download attached media and build the agent-visible content."""
        caption = message.text or (message.media.caption if message.media else "")
        if message.media is None or not self.config.download_media:
            return [], caption

        path = await self._download_media(message)
        if path is None:
            placeholder = _MEDIA_PLACEHOLDERS.get(message.kind, "[attachment]")
            return [], caption or placeholder

        if message.kind == "audio" and message.media.voice:
            # Voice notes are transcribed when a provider is configured; the
            # file stays attached so the agent can still inspect it.
            transcription = (await self.transcribe_audio(path)).strip()
            if transcription:
                return [str(path)], transcription
            return [str(path)], caption or "[voice note]"

        content = caption
        if not content:
            label = _MEDIA_PLACEHOLDERS.get(message.kind, "[attachment]")
            if message.media.filename:
                content = f"{label} {message.media.filename}"
            else:
                content = label
        return [str(path)], content

    # ------------------------------------------------------------------
    # Media download
    # ------------------------------------------------------------------

    async def _download_media(self, message: PlatformMessage) -> Path | None:
        """Fetch inbound media bytes and store them under the media directory."""
        media = message.media
        if media is None:
            return None

        limit = min(
            media_limit_for(media.mime_type, message.kind),
            self.config.max_media_mb * 1024 * 1024,
        )
        try:
            metadata = await self._request_ok(
                "GET", f"/media/{media.media_id}", method_key="media"
            )
        except WhatsAppAgentAuthError:
            raise
        except Exception as exc:
            self.logger.warning(
                "Could not fetch metadata for media {}: {}", media.media_id, exc
            )
            return None

        metadata_map = cast(dict[str, Any], metadata) if isinstance(metadata, dict) else {}
        url = str(metadata_map.get("url") or "")
        safe, reason = quote_safe_url(url)
        if not safe:
            self.logger.error("Refusing unsafe WhatsApp Agent media URL: {}", reason)
            return None

        try:
            content = await self._fetch_media_bytes(url, limit)
        except Exception as exc:
            self.logger.warning("Media download failed for {}: {}", media.media_id, exc)
            return None

        if not self._digest_matches(media, content):
            self.logger.error(
                "Discarding WhatsApp Agent media {}: sha256 mismatch", media.media_id
            )
            return None

        path = self._media_target(message)
        try:
            path.write_bytes(content)
        except OSError:
            self.logger.exception("Failed to store WhatsApp Agent media")
            return None

        if self.config.delete_media_after_download:
            with suppress(Exception):
                await self._request(
                    "DELETE", f"/media/{media.media_id}", method_key="media"
                )
        return path

    async def _fetch_media_bytes(self, url: str, limit: int) -> bytes:
        """Download media bytes with the bearer token and a hard size cap."""
        client = self._client
        if client is None:
            raise RuntimeError("WhatsApp Agent Platform channel is not connected")
        await self._limiter.acquire("media")
        async with client.stream(
            "GET", url, headers=self._auth_headers(), follow_redirects=False
        ) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise ValueError(f"declared media size exceeds the {limit}-byte limit")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"media exceeds the {limit}-byte limit")
                chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _digest_matches(media: InboundMedia, content: bytes) -> bool:
        """Verify the platform digest, which is Base64 inbound and hex in metadata."""
        if not media.sha256_base64:
            return True
        import base64

        try:
            # Inbound payloads carry the digest Base64-encoded; the media
            # metadata endpoint returns the same digest as hex.
            expected = base64.b64decode(media.sha256_base64, validate=True)
        except Exception:
            try:
                expected = bytes.fromhex(media.sha256_base64)
            except ValueError:
                return True
        return hashlib.sha256(content).digest() == expected

    def _media_target(self, message: PlatformMessage) -> Path:
        from nanobot.config.paths import get_media_dir

        media = message.media
        assert media is not None
        suffix = Path(media.filename).suffix if media.filename else ""
        if not suffix:
            suffix = mimetypes.guess_extension(media.mime_type or "") or ".bin"
        name = safe_filename(Path(media.filename).stem) if media.filename else message.wamid
        digest = hashlib.sha256(message.wamid.encode("utf-8")).hexdigest()[:12]
        return get_media_dir(self.name) / f"{name}-{digest}{suffix}"

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def _recipient(self) -> str:
        """Return the creator identifier the API accepts in ``to``."""
        if self._state.creator_id:
            return self._state.creator_id
        return ""

    async def send(self, msg: OutboundMessage) -> None:
        """Deliver one outbound message, chunked to the API text limit."""
        if isinstance(msg.event, ContextCompactionEvent) and not (
            msg.event.notify or self.show_compaction_notices
        ):
            return
        if isinstance(msg.event, ProgressEvent):
            # Progress is disabled by default; never spend send budget on it.
            return

        to = self._recipient()
        if not to:
            raise WhatsAppAgentAPIError(
                APIError(
                    status_code=0,
                    code=0,
                    message="No creator identifier is known yet; wait for an inbound message.",
                    details="",
                    fbtrace_id="",
                )
            )

        # The reply implicitly clears the typing indicator.
        await self._stop_typing()

        quote = msg.metadata.get("message_id") or msg.metadata.get("origin_message_id")
        reply_to = quote if isinstance(quote, str) and quote else None

        chunks = split_message(msg.content, TEXT_MAX_CHARS)
        for index, chunk in enumerate(chunks):
            await self._send_text(to, chunk, reply_to if index == 0 else None)

        for media_path in msg.media or []:
            await self._send_media(to, media_path)

    async def _send_text(self, to: str, body: str, reply_to: str | None) -> None:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        if reply_to:
            # Inbound quotes use ``id``; outbound quoting uses ``message_id``.
            payload["context"] = {"message_id": reply_to}
        response = await self._request_ok(
            "POST", "/messages", method_key="messages", json_body=payload
        )
        self._remember_sent(response)

    def _remember_sent(self, response: Any) -> None:
        """Record the outbound wamid that later receipts refer to."""
        if not isinstance(response, dict):
            return
        body = cast(dict[str, Any], response)
        raw_messages = body.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            return
        first = cast(list[object], raw_messages)[0]
        if not isinstance(first, dict):
            return
        wamid = str(cast(dict[str, Any], first).get("id") or "")
        if wamid:
            self._state.note_status(wamid, "sent")

    async def _send_media(self, to: str, media_path: str) -> None:
        """Upload a local file and send it as the matching message type."""
        path = Path(media_path).expanduser()
        if not path.is_file():
            self.logger.warning("Skipping missing WhatsApp Agent media: {}", media_path)
            return
        size = path.stat().st_size
        mime_type = self._detect_mime(path)
        kind = outbound_kind_for_mime(mime_type)
        limit = media_limit_for(mime_type, kind)
        if size > limit:
            self.logger.error(
                "Skipping {} ({} bytes) for {}: exceeds the {}-byte limit",
                path.name,
                size,
                kind,
                limit,
            )
            return
        if mime_type not in ACCEPTED_UPLOAD_MIME:
            # The generic binary type is accepted for any file up to 16 MB.
            mime_type = "application/octet-stream"

        media_id = await self._upload_media(path, mime_type)
        if kind == "sticker":
            # Stickers reject captions and extra payload objects.
            media_object: dict[str, Any] = {"id": media_id}
        elif kind == "document":
            media_object = {"id": media_id, "filename": path.name}
        elif kind == "audio":
            media_object = {"id": media_id}
        else:
            media_object = {"id": media_id}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": kind,
            # Only the object matching ``type`` is sent, but the others are
            # still validated, so no extra payload objects are included.
            kind: media_object,
        }
        response = await self._request_ok(
            "POST", "/messages", method_key="messages", json_body=payload
        )
        self._remember_sent(response)

    async def _upload_media(self, path: Path, mime_type: str) -> str:
        with path.open("rb") as handle:
            payload = await self._request_ok(
                "POST",
                "/media",
                method_key="media",
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (path.name, handle, mime_type)},
            )
        payload_map = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        media_id = str(payload_map.get("id") or "")
        if not media_id:
            raise WhatsAppAgentAPIError(
                APIError(
                    status_code=0,
                    code=0,
                    message="Media upload returned no id",
                    details="",
                    fbtrace_id="",
                )
            )
        return media_id

    @staticmethod
    def _detect_mime(path: Path) -> str:
        guessed, _ = mimetypes.guess_type(path.name)
        return normalize_mime(guessed or "application/octet-stream")


__all__ = [
    "AUTH_FAILURE_MESSAGE",
    "CREATOR_CHAT_ID",
    "WhatsAppAgentChannel",
    "WhatsAppAgentConfig",
    "token_fingerprint",
]
