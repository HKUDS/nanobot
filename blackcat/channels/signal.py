"""Signal channel implementation using signal-cli daemon JSON-RPC interface."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import unicodedata
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field, computed_field, field_validator

from blackcat.bus.events import InboundMessage, OutboundMessage
from blackcat.bus.queue import MessageBus
from blackcat.channels.base import BaseChannel
from blackcat.config.paths import get_media_dir
from blackcat.config.schema import Base
from blackcat.pairing import is_approved
from blackcat.utils.formatting import split_message
from blackcat.utils.helpers import safe_filename


@dataclass
class _Run:
    text: str
    styles: frozenset[str] = field(default_factory=frozenset)
    opaque: bool = False  # code / table content — skip further pattern processing


_SIG_CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\n?([\s\S]*?)```")
_SIG_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_SIG_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_SIG_BLOCKQUOTE_RE = re.compile(r"^>\s*(.*)$", re.MULTILINE)
_SIG_BULLET_RE = re.compile(r"^[-*]\s+", re.MULTILINE)
_SIG_OLIST_RE = re.compile(r"^(\d+)\.\s+", re.MULTILINE)
_SIG_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_SIG_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_SIG_ITALIC_RE = re.compile(
    r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<![a-zA-Z0-9_])_([^_\n]+)_(?![a-zA-Z0-9_])"
)
_SIG_STRIKE_RE = re.compile(r"~~(.+?)~~|(?<![~\w])~([^~\n]+)~(?![~\w])", re.DOTALL)
_SIG_TOKEN_RE = re.compile(r"\x00C(\d+)\x00")

# Patterns used to strip inline markdown when rendering table cells as plain
# text. Defined separately from the styling regexes above because the cell
# stripper needs a fixed, narrow subset (no single-asterisk italic, no
# single-tilde strikethrough) and benefits from each pattern's group 1 being
# the content directly.
_SIG_CELL_STRIP_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
    (re.compile(r"`([^`]+)`"), r"\1"),
)


def _utf16_len(s: str) -> int:
    """UTF-16 code-unit length, matching Signal BodyRange semantics."""
    return len(s.encode("utf-16-le")) // 2


def _sig_strip_cell(s: str) -> str:
    """Strip inline markdown from a table cell for plain-text rendering."""
    for pattern, repl in _SIG_CELL_STRIP_PATTERNS:
        s = pattern.sub(repl, s)
    return s.strip()


def _sig_render_table(table_lines: list[str]) -> str:
    """Render a markdown pipe-table as fixed-width plain text."""

    def dw(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_sig_strip_cell(c) for c in line.strip().strip("|").split("|")]
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):
            has_sep = True
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return "\n".join(table_lines)

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (ncols - len(r)))
    widths = [max(dw(r[c]) for r in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        return "  ".join(f"{c}{' ' * (w - dw(c))}" for c, w in zip(cells, widths))

    out = [dr(rows[0])]
    out.append("  ".join("─" * w for w in widths))
    for row in rows[1:]:
        out.append(dr(row))
    return "\n".join(out)


def _markdown_to_signal(text: str) -> tuple[str, list[str]]:
    """Convert markdown text to Signal plain text + textStyle ranges.

    Returns ``(plain_text, text_styles)`` where ``text_styles`` are
    ``"start:length:STYLE"`` strings for the signal-cli ``textStyle`` parameter.
    """
    if not text:
        return text, []

    # Phase 1 (text-level): extract code blocks and tables with placeholder tokens
    # so they're protected from inline-style processing.
    protected: list[str] = []

    def save_code(m: re.Match) -> str:
        protected.append(m.group(1))
        return f"\x00C{len(protected) - 1}\x00"

    text = _SIG_CODE_BLOCK_RE.sub(save_code, text)

    # Detect and render pipe-tables line by line.
    lines = text.split("\n")
    rebuilt: list[str] = []
    i = 0
    while i < len(lines):
        if re.match(r"^\s*\|.+\|", lines[i]):
            tbl: list[str] = []
            while i < len(lines) and re.match(r"^\s*\|.+\|", lines[i]):
                tbl.append(lines[i])
                i += 1
            rendered = _sig_render_table(tbl)
            if rendered != "\n".join(tbl):
                protected.append(rendered)
                rebuilt.append(f"\x00C{len(protected) - 1}\x00")
            else:
                rebuilt.extend(tbl)
        else:
            rebuilt.append(lines[i])
            i += 1
    text = "\n".join(rebuilt)

    # Phase 2 (run-based): process inline patterns.
    runs: list[_Run] = [_Run(text)]

    def transform(
        pattern: re.Pattern,
        make_runs: Callable[[re.Match, frozenset[str]], list[_Run]],
    ) -> None:
        new_runs: list[_Run] = []
        for run in runs:
            if run.opaque:
                new_runs.append(run)
                continue
            pos = 0
            for m in pattern.finditer(run.text):
                if m.start() > pos:
                    new_runs.append(_Run(run.text[pos : m.start()], run.styles))
                new_runs.extend(make_runs(m, run.styles))
                pos = m.end()
            if pos < len(run.text):
                new_runs.append(_Run(run.text[pos:], run.styles))
        runs[:] = new_runs

    # Restore code/table placeholders as opaque MONOSPACE runs.
    transform(
        _SIG_TOKEN_RE,
        lambda m, s: [_Run(protected[int(m.group(1))], s | {"MONOSPACE"}, opaque=True)],
    )

    # Inline code (opaque).
    transform(_SIG_INLINE_CODE_RE, lambda m, s: [_Run(m.group(1), s | {"MONOSPACE"}, opaque=True)])

    # Headers → bold plain text.
    transform(_SIG_HEADER_RE, lambda m, s: [_Run(m.group(1), s | {"BOLD"})])

    # Blockquotes → strip marker.
    transform(_SIG_BLOCKQUOTE_RE, lambda m, s: [_Run(m.group(1), s)])

    # Bullet lists → bullet character.
    transform(_SIG_BULLET_RE, lambda m, s: [_Run("• ", s)])

    # Numbered lists → normalize spacing.
    transform(_SIG_OLIST_RE, lambda m, s: [_Run(m.group(1) + ". ", s)])

    # Links → "text (url)" or bare url when text equals url.
    def _link_runs(m: re.Match, s: frozenset) -> list[_Run]:
        link_text, url = m.group(1), m.group(2)

        def _norm(u: str) -> str:
            return re.sub(r"^https?://(www\.)?", "", u).rstrip("/").lower()

        if _norm(url) == _norm(link_text):
            return [_Run(url, s)]
        return [_Run(f"{link_text} ({url})", s)]

    transform(_SIG_LINK_RE, _link_runs)

    # Bold (before italic so ** doesn't interfere).
    transform(_SIG_BOLD_RE, lambda m, s: [_Run(m.group(1) or m.group(2), s | {"BOLD"})])

    # Italic (single * or _).
    transform(_SIG_ITALIC_RE, lambda m, s: [_Run(m.group(1) or m.group(2), s | {"ITALIC"})])

    # Strikethrough: ~~text~~ (standard) or ~text~ (single-tilde variant).
    transform(_SIG_STRIKE_RE, lambda m, s: [_Run(m.group(1) or m.group(2), s | {"STRIKETHROUGH"})])

    # Phase 3: assemble output. Offsets and lengths are emitted in UTF-16 code
    # units because Signal's BodyRange (via signal-cli's textStyle) interprets
    # them as such; Python's len() counts code points, which would shift ranges
    # left by 1 unit per non-BMP character preceding them.
    plain_text = ""
    text_styles: list[str] = []
    utf16_offset = 0
    for run in runs:
        if not run.text:
            continue
        plain_text += run.text
        start = utf16_offset
        length = _utf16_len(run.text)
        utf16_offset += length
        for style in sorted(run.styles):
            text_styles.append(f"{start}:{length}:{style}")

    return plain_text, text_styles


def _partition_styles(
    plain_text: str, chunks: list[str], text_styles: list[str]
) -> list[list[str]]:
    """Partition Signal textStyle ranges across message chunks.

    ``split_message`` slices ``plain_text`` into pieces (optionally trimming
    whitespace at the boundaries), but the style ranges produced by
    ``_markdown_to_signal`` are expressed in UTF-16 offsets relative to the
    full ``plain_text``. This redistributes them per chunk with offsets
    rebased to each chunk's start. Ranges that span a boundary are split
    across the chunks they touch; ranges that fall entirely in trimmed
    whitespace are dropped.
    """
    if not chunks:
        return []
    if not text_styles:
        return [[] for _ in chunks]

    # Locate each chunk's UTF-16 start in plain_text. split_message lstrips at
    # boundaries (but not before the first chunk), so we skip whitespace
    # between chunks to mirror that.
    chunk_ranges: list[tuple[int, int]] = []
    cursor = 0  # Python codepoint cursor in plain_text
    for i, chunk in enumerate(chunks):
        if i > 0:
            while cursor < len(plain_text) and plain_text[cursor].isspace():
                cursor += 1
        utf16_start = _utf16_len(plain_text[:cursor])
        utf16_end = utf16_start + _utf16_len(chunk)
        chunk_ranges.append((utf16_start, utf16_end))
        cursor += len(chunk)

    result: list[list[str]] = [[] for _ in chunks]
    for entry in text_styles:
        s, ln, style = entry.split(":", 2)
        r_start = int(s)
        r_end = r_start + int(ln)
        for i, (c_start, c_end) in enumerate(chunk_ranges):
            if r_end <= c_start or r_start >= c_end:
                continue
            new_start = max(r_start, c_start) - c_start
            new_end = min(r_end, c_end) - c_start
            new_length = new_end - new_start
            if new_length > 0:
                result[i].append(f"{new_start}:{new_length}:{style}")
    return result


class SignalDMConfig(Base):
    """Signal DM policy configuration."""

    enabled: bool = False
    policy: str = "allowlist"  # "open" or "allowlist"
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers/UUIDs


class SignalGroupConfig(Base):
    """Signal group policy configuration."""

    enabled: bool = False
    policy: str = "allowlist"  # "open" or "allowlist" - which groups to operate in
    allow_from: list[str] = Field(default_factory=list)  # Allowed group IDs if allowlist policy
    require_mention: bool = True  # Whether bot must be mentioned to respond


class SignalConfig(Base):
    """Signal channel configuration using signal-cli daemon (HTTP mode with -a flag only)."""

    enabled: bool = False
    phone_number: str = ""  # Your Signal phone number (e.g., "+1234567890")
    daemon_host: str = "localhost"
    daemon_port: int = 8080
    group_message_buffer_size: int = 20  # Number of recent group messages to keep for context
    # Override the directory signal-cli writes inbound attachments to. When
    # None, defaults to ~/.local/share/signal-cli/attachments (the daemon's
    # platform default on Linux). Set this if the daemon is running with a
    # custom XDG_DATA_HOME or on macOS/Windows where the default path differs.
    attachments_dir: str | None = None
    dm: SignalDMConfig = Field(default_factory=SignalDMConfig)
    group: SignalGroupConfig = Field(default_factory=SignalGroupConfig)

    @field_validator("group_message_buffer_size")
    @classmethod
    def _validate_buffer_size(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("group_message_buffer_size must be > 0")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allow_from(self) -> list[str]:
        """Aggregate allowlist for the base-class is_allowed() check.

        Returns the union of dm.allow_from and group.allow_from so the base
        channel gate sees a populated list when either sub-policy is configured.
        A ``"*"`` wildcard in either sub-list propagates to allow all.
        """
        return list(dict.fromkeys(self.dm.allow_from + self.group.allow_from))


class SignalChannel(BaseChannel):
    """
    Signal channel using signal-cli daemon via HTTP JSON-RPC interface.

    Requires signal-cli daemon in HTTP mode:
    - signal-cli -a +1234567890 daemon --http localhost:8080

    See https://github.com/AsamK/signal-cli for setup instructions.
    """

    name = "signal"
    display_name = "Signal"
    _TYPING_REFRESH_SECONDS = 10.0
    _MAX_MESSAGE_LEN = 64_000  # signal-cli practical limit (protocol max ~64 KB)
    _HTTP_TIMEOUT_SECONDS = 60.0

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SignalConfig().model_dump(by_alias=True)

    def __init__(self, config: SignalConfig, bus: MessageBus):
        if isinstance(config, dict):
            config = SignalConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: SignalConfig = config
        self._http: httpx.AsyncClient | None = None
        self._request_id = 0
        self._sse_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._typing_uuid_warnings: set[str] = set()
        self._account_id_aliases: set[str] = set()
        self._remember_account_id_alias(self.config.phone_number)

        # Rolling message buffer for group context (group_id -> deque of messages)
        # Each message is a dict with: sender_name, sender_number, content, timestamp
        self._group_buffers: dict[str, deque] = {}

    def is_allowed(self, sender_id: str) -> bool:
        """Override base check to normalize and split pipe-joined identifiers.

        ``sender_id`` from Signal is the pipe-joined composite produced by
        ``_collect_sender_id_parts``; allow_from entries may be single
        identifiers or composites and may use the ``+`` prefix variant or
        not. Delegates to ``_sender_matches_allowlist`` so the base gate
        matches the per-policy DM gate.
        """
        allow_list = self.config.allow_from
        if "*" in allow_list:
            return True
        if self._sender_matches_allowlist(sender_id, allow_list):
            return True
        if self._sender_approved_via_pairing(sender_id):
            return True
        if not allow_list:
            self.logger.warning("allow_from is empty — all access denied")
        return False

    def _sender_approved_via_pairing(self, sender_id: str) -> bool:
        """Return True if any normalized variant of sender_id is in the pairing store.

        Pairing approval may be recorded under any of the identifier forms
        signal exposes (phone with/without ``+``, UUID, ACI), so we check
        each part of the pipe-joined composite against ``is_approved``.
        """
        for part in str(sender_id).split("|"):
            for variant in self._normalize_signal_id(part):
                if is_approved(self.name, variant):
                    return True
        return False

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
        is_dm: bool = False,
    ) -> None:
        """Handle an inbound message whose policy has already been checked.

        ``_check_inbound_policy`` is the authoritative gate for DM/group
        access, so we skip the base-class ``is_allowed()`` check and publish
        directly to the bus.  The denied-DM pairing path calls
        ``super()._handle_message`` instead, which goes through
        ``is_allowed`` and issues a pairing code.
        """
        meta = metadata or {}
        if self.supports_streaming:
            meta = {**meta, "_wants_stream": True}
        await self.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                sender_id=str(sender_id),
                chat_id=str(chat_id),
                content=content,
                media=media or [],
                metadata=meta,
                session_key_override=session_key,
            )
        )

    async def start(self) -> None:
        """Start the Signal channel and connect to signal-cli daemon."""
        if not self.config.phone_number:
            self.logger.error("Signal account not configured")
            return

        self._running = True
        await self._start_http_mode()

    async def _start_http_mode(self) -> None:
        """Start Signal channel using Server-Sent Events for receiving messages."""
        base_url = f"http://{self.config.daemon_host}:{self.config.daemon_port}"
        reconnect_delay_s = 1.0
        max_reconnect_delay_s = 30.0

        while self._running:
            try:
                self.logger.info("Connecting to signal-cli daemon at {}...", base_url)

                # Create HTTP client
                self._http = httpx.AsyncClient(
                    timeout=self._HTTP_TIMEOUT_SECONDS, base_url=base_url
                )

                # Test connection
                try:
                    response = await self._http.get("/api/v1/check")
                    if response.status_code == 200:
                        self.logger.info("Connected to signal-cli daemon")
                    else:
                        raise ConnectionRefusedError(
                            f"signal-cli daemon check returned status {response.status_code}"
                        )
                except Exception as e:
                    raise ConnectionRefusedError(f"signal-cli daemon not responding: {e}")

                # Reset reconnect delay after successful connection check.
                reconnect_delay_s = 1.0

                # Ensure account-level typing indicators are enabled.
                await self._ensure_typing_indicators_enabled()

                # Start SSE receiver and supervise it. If it exits while we're still
                # running, treat it as a disconnect and reconnect.
                self._sse_task = asyncio.create_task(self._sse_receive_loop())
                await self._sse_task
                if self._running:
                    raise ConnectionError("Signal SSE stream ended unexpectedly")

            except asyncio.CancelledError:
                break
            except ConnectionRefusedError as e:
                self.logger.error(
                    "{}. Make sure signal-cli daemon is running: "
                    "signal-cli -a {} daemon --http {}:{}",
                    e,
                    self.config.phone_number,
                    self.config.daemon_host,
                    self.config.daemon_port,
                )
            except Exception as e:
                self.logger.error("Signal channel error: {}", e)
            finally:
                if self._sse_task:
                    if not self._sse_task.done():
                        self._sse_task.cancel()
                    try:
                        await self._sse_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                    self._sse_task = None
                if self._http:
                    await self._http.aclose()
                    self._http = None

            if self._running:
                self.logger.info(
                    "Reconnecting to signal-cli daemon in {:.0f} seconds...", reconnect_delay_s
                )
                await asyncio.sleep(reconnect_delay_s)
                reconnect_delay_s = min(reconnect_delay_s * 2, max_reconnect_delay_s)

    async def stop(self) -> None:
        """Stop the Signal channel."""
        self._running = False

        # Stop SSE task
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass

        # Cancel active typing indicators
        for chat_id in list(self._typing_tasks):
            await self._stop_typing(chat_id)

        # Close HTTP client
        if self._http:
            await self._http.aclose()
            self._http = None

    async def _send_impl(self, msg: OutboundMessage) -> None:
        """Send a message through Signal."""
        is_progress_message = bool(msg.metadata.get("_progress"))
        try:
            plain_text, text_styles = _markdown_to_signal(msg.content)
            if not plain_text and not msg.media:
                return
            recipient_params = self._recipient_params(msg.chat_id)

            chunks = split_message(plain_text, self._MAX_MESSAGE_LEN) if plain_text else [""]
            chunk_styles = _partition_styles(plain_text, chunks, text_styles)
            for i, chunk in enumerate(chunks):
                params: dict[str, Any] = {"message": chunk}
                if chunk_styles[i]:
                    params["textStyle"] = chunk_styles[i]
                params.update(recipient_params)
                if msg.media and i == 0:
                    params["attachments"] = msg.media

                response = await self._send_request("send", params)

                if "error" in response:
                    self.logger.error("Error sending Signal message: {}", response['error'])
                    raise RuntimeError(f"signal-cli send failed: {response['error']}")
                else:
                    self.logger.debug(
                        f"Signal message sent, timestamp: {response.get('result', {}).get('timestamp')}"
                    )

        except Exception:
            self.logger.exception("Error sending Signal message")
            raise
        finally:
            # Keep typing active across progress updates; stop on the final reply.
            if not is_progress_message:
                # Avoid immediate START->STOP for fast responses, which can be invisible
                # in some Signal clients. Let indicator expire naturally (~15s).
                await self._stop_typing(msg.chat_id, send_stop=False)

    async def _sse_receive_loop(self) -> None:
        """Receive messages via Server-Sent Events (HTTP mode)."""
        if not self._http:
            raise RuntimeError("HTTP client not initialized for Signal SSE stream")

        self.logger.info("Started Signal message receive loop (SSE)")

        try:
            async with self._http.stream("GET", "/api/v1/events") as response:
                if response.status_code != 200:
                    raise ConnectionError(
                        f"SSE connection failed with status {response.status_code}"
                    )

                self.logger.info("Subscribed to Signal messages via SSE")

                # Buffer for accumulating SSE data across multiple lines
                event_buffer = []

                async for line in response.aiter_lines():
                    if not self._running:
                        break

                    # Debug: log raw SSE lines (except keepalive pings)
                    if line and line != ":":
                        self.logger.debug("SSE line received: {}", line[:200])

                    # SSE format handling
                    if isinstance(line, str):
                        # Empty line signals end of event
                        if not line or line == ":":
                            if event_buffer:
                                # Try to parse the accumulated data
                                data_str = ""
                                try:
                                    data_str = "\n".join(event_buffer)
                                    data = json.loads(data_str)
                                    self.logger.debug("SSE event parsed: {}", data)
                                    await self._handle_receive_notification(data)
                                except json.JSONDecodeError as e:
                                    self.logger.warning(
                                        "Invalid JSON in SSE buffer: {}, data: {}",
                                        e,
                                        data_str[:200],
                                    )
                                finally:
                                    event_buffer = []

                        # "data:" line - accumulate it
                        elif line.startswith("data:"):
                            # SSE spec: strip one optional leading space after "data:".
                            event_buffer.append(line[6:] if line[5:6] == " " else line[5:])

                        # "event:" line - just log it (we only care about data)
                        elif line.startswith("event:"):
                            pass  # Ignore event type for now

                if self._running:
                    raise ConnectionError("Signal SSE stream closed by remote endpoint")

        except asyncio.CancelledError:
            self.logger.info("SSE receive loop cancelled")
            raise
        except Exception as e:
            self.logger.error("Error in SSE receive loop: {}", e)
            raise

    @asynccontextmanager
    async def _safe_handle(self, action: str, payload: Any = None) -> AsyncIterator[None]:
        """Swallow and log any exception from a top-level handler block.

        Logs `self.logger.error` with the action name, the exception, and a
        bounded ``repr`` of the offending payload so the offending input is
        recoverable from logs without having to correlate by timestamp.
        """
        try:
            yield
        except Exception as e:
            snippet = repr(payload)[:200] if payload is not None else ""
            text = f"Error in {action}: {e}"
            if snippet:
                text += f" | payload={snippet}"
            self.logger.opt(exception=True).error(text)

    async def _handle_receive_notification(self, params: dict[str, Any]) -> None:
        """Handle incoming message notification from signal-cli."""
        self.logger.debug("_handle_receive_notification called with: {}", params)
        async with self._safe_handle("receive notification", params):
            # Extract envelope from SSE notification: {"envelope": {...}}
            envelope = params.get("envelope", {})

            self.logger.debug("Extracted envelope: {}", envelope)

            if not envelope:
                self.logger.debug("No envelope found in params")
                return

            # Extract sender information
            sender_parts = self._collect_sender_id_parts(envelope)
            source_name = envelope.get("sourceName")

            if not sender_parts:
                self.logger.debug("Received message without source, skipping")
                return

            sender_number = self._primary_sender_id(sender_parts)
            sender_id = "|".join(sender_parts)

            # Keep aliases of the bot account for robust mention matching.
            if any(self._id_matches_account(part) for part in sender_parts):
                for part in sender_parts:
                    self._remember_account_id_alias(part)

            # Check different message types
            data_message = envelope.get("dataMessage")
            sync_message = envelope.get("syncMessage")
            typing_message = envelope.get("typingMessage")
            receipt_message = envelope.get("receiptMessage")

            # Ignore receipt messages (delivery/read receipts)
            if receipt_message:
                return

            # Handle data messages (incoming messages from others)
            if data_message:
                await self._handle_data_message(sender_id, sender_number, data_message, source_name)

            # Handle sync messages (messages sent from another device)
            elif sync_message and sync_message.get("sentMessage"):
                sent_msg = sync_message["sentMessage"]
                destination = sent_msg.get("destination") or sent_msg.get("destinationNumber")
                if destination:
                    self.logger.debug(
                        "Sync message sent to {}: {}", destination, sent_msg.get("message", "")[:50]
                    )

            # Handle typing indicators (silently ignore)
            elif typing_message:
                pass  # Ignore typing indicators

    async def _handle_data_message(
        self,
        sender_id: str,
        sender_number: str,
        data_message: dict[str, Any],
        sender_name: str | None,
    ) -> None:
        """Handle a data message (text, attachments, etc.)."""
        message_text = data_message.get("message") or ""
        attachments = data_message.get("attachments", [])
        mentions = data_message.get("mentions", [])
        timestamp = data_message.get("timestamp")

        self.logger.info(
            "Data message from {}: groupInfo={}, groupV2={}, keys={}",
            sender_number,
            data_message.get("groupInfo"),
            data_message.get("groupV2"),
            list(data_message.keys()),
        )

        if data_message.get("reaction"):
            self.logger.debug(
                "Ignoring reaction message from {}: {}", sender_number, data_message["reaction"]
            )
            return
        if not message_text and not attachments:
            self.logger.debug("Ignoring empty message from {}", sender_number)
            return

        group_info = data_message.get("groupInfo")
        group_v2 = data_message.get("groupV2")
        is_group_message = group_info is not None or group_v2 is not None
        group_id = self._extract_group_id(group_info, group_v2)

        allowed, chat_id = self._check_inbound_policy(
            sender_id=sender_id,
            sender_number=sender_number,
            group_id=group_id,
            is_group_message=is_group_message,
            message_text=message_text,
            mentions=mentions,
            sender_name=sender_name,
            timestamp=timestamp,
        )
        if not allowed:
            # Mirror Slack: let denied DMs reach the base-class
            # _handle_message so it can reply with a pairing code.
            # Group denials stay dropped.
            if not is_group_message and self.config.dm.enabled:
                await super()._handle_message(
                    sender_id=sender_id,
                    chat_id=chat_id,
                    content="",
                    is_dm=True,
                )
            return

        content, media_paths = self._assemble_inbound_content(
            sender_name=sender_name,
            sender_number=sender_number,
            message_text=message_text,
            attachments=attachments,
            mentions=mentions,
            is_group_message=is_group_message,
            chat_id=chat_id,
        )

        self.logger.debug("Signal message from {}: {}...", sender_number, content[:50])

        await self._start_typing(chat_id)
        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media_paths,
                metadata={
                    "timestamp": timestamp,
                    "sender_name": sender_name,
                    "sender_number": sender_number,
                    "is_group": is_group_message,
                    "group_id": group_id,
                },
                is_dm=not is_group_message,
            )
        except Exception:
            await self._stop_typing(chat_id)
            raise

    def _check_inbound_policy(
        self,
        *,
        sender_id: str,
        sender_number: str,
        group_id: str | None,
        is_group_message: bool,
        message_text: str,
        mentions: list,
        sender_name: str | None,
        timestamp: int | None,
    ) -> tuple[bool, str]:
        """Decide whether to route an inbound message past DM/group policy.

        Returns ``(allow, chat_id)``. Has one side effect: when a group
        message passes the enabled+allowlist gates, it is appended to the
        group's rolling context buffer before the mention check.
        """
        if is_group_message:
            chat_id = group_id or sender_number
            if not self.config.group.enabled:
                self.logger.info("Ignoring group message from {} (groups disabled)", chat_id)
                return False, chat_id
            if (
                self.config.group.policy == "allowlist"
                and chat_id not in self.config.group.allow_from
            ):
                self.logger.info(
                    "Ignoring group message from {} (policy: {})",
                    chat_id,
                    self.config.group.policy,
                )
                return False, chat_id

            self._add_to_group_buffer(
                group_id=chat_id,
                sender_name=sender_name or sender_number,
                sender_number=sender_number,
                message_text=message_text,
                timestamp=timestamp,
            )

            is_command = bool(message_text and message_text.strip().startswith("/"))
            if not is_command and not self._should_respond_in_group(message_text, mentions):
                self.logger.info(
                    "Ignoring group message (require_mention: {})",
                    self.config.group.require_mention,
                )
                return False, chat_id
            return True, chat_id

        # Direct message
        chat_id = sender_number
        if not self.config.dm.enabled:
            self.logger.debug("Ignoring DM from {} (DMs disabled)", sender_id)
            return False, chat_id
        if self.config.dm.policy == "allowlist":
            if not self._sender_matches_allowlist(sender_id, self.config.dm.allow_from):
                self.logger.debug(
                    "Ignoring DM from {} (policy: {})", sender_id, self.config.dm.policy
                )
                return False, chat_id
        return True, chat_id

    def _assemble_inbound_content(
        self,
        *,
        sender_name: str | None,
        sender_number: str,
        message_text: str,
        attachments: list,
        mentions: list,
        is_group_message: bool,
        chat_id: str,
    ) -> tuple[str, list[str]]:
        """Build ``(content, media_paths)`` for an inbound message.

        Pulls in group context, strips bot mentions, prefixes the sender's
        display name on group messages, and copies any attachments from
        signal-cli's storage into the channel media dir.
        """
        content_parts: list[str] = []
        media_paths: list[str] = []

        if is_group_message:
            buffer_context = self._get_group_buffer_context(chat_id)
            if buffer_context:
                content_parts.append(f"[Recent group messages for context:]\n{buffer_context}\n---")

        if message_text:
            if is_group_message:
                message_text = self._strip_bot_mention(message_text, mentions)
                display_name = sender_name or sender_number
                message_text = f"[{display_name}]: {message_text}"
            content_parts.append(message_text)

        if attachments:
            media_dir = get_media_dir("signal")
            for attachment in attachments:
                attachment_id = attachment.get("id")
                content_type = attachment.get("contentType", "")
                filename = attachment.get("filename") or f"attachment_{attachment_id}"
                if not attachment_id:
                    continue
                try:
                    source_path = self._signal_attachments_dir() / attachment_id
                    if source_path.exists():
                        dest_path = media_dir / f"signal_{safe_filename(filename)}"
                        shutil.copy2(source_path, dest_path)
                        media_paths.append(str(dest_path))
                        media_type = content_type.split("/")[0] if "/" in content_type else "file"
                        if media_type not in ("image", "audio", "video"):
                            media_type = "file"
                        content_parts.append(f"[{media_type}: {dest_path}]")
                        self.logger.debug("Downloaded attachment: {} -> {}", filename, dest_path)
                    else:
                        self.logger.warning("Attachment not found: {}", source_path)
                        content_parts.append(f"[attachment: {filename} - not found]")
                except Exception as e:
                    self.logger.warning("Failed to process attachment {}: {}", filename, e)
                    content_parts.append(f"[attachment: {filename} - error]")

        content = "\n".join(content_parts) if content_parts else "[empty message]"
        return content, media_paths

    def _add_to_group_buffer(
        self,
        group_id: str,
        sender_name: str,
        sender_number: str,
        message_text: str,
        timestamp: int | None,
    ) -> None:
        """
        Add a message to the group's rolling buffer.

        Args:
            group_id: The group ID
            sender_name: Display name of sender
            sender_number: Phone number of sender
            message_text: The message content
            timestamp: Message timestamp
        """
        # Create buffer for this group if it doesn't exist
        if group_id not in self._group_buffers:
            self._group_buffers[group_id] = deque(maxlen=self.config.group_message_buffer_size)

        # Add message to buffer (deque will automatically drop oldest when full)
        self._group_buffers[group_id].append(
            {
                "sender_name": sender_name,
                "sender_number": sender_number,
                "content": message_text,
                "timestamp": timestamp,
            }
        )

        self.logger.debug(
            "Added message to group buffer {}: {}/{}",
            group_id,
            len(self._group_buffers[group_id]),
            self.config.group_message_buffer_size,
        )

    def _get_group_buffer_context(self, group_id: str) -> str:
        """
        Get formatted context from the group's message buffer.

        Args:
            group_id: The group ID

        Returns:
            Formatted string of recent messages (excluding the current one)
        """
        if group_id not in self._group_buffers:
            return ""

        buffer = self._group_buffers[group_id]
        if len(buffer) <= 1:  # Only current message, no context
            return ""

        # Format all messages except the last one (which is the current message)
        # We want to show context BEFORE the mention
        context_messages = list(buffer)[:-1]  # Exclude the last (current) message

        lines = []
        for msg in context_messages:
            sender = msg["sender_name"]
            content = msg["content"][:200]  # Limit to 200 chars per message
            lines.append(f"{sender}: {content}")

        return "\n".join(lines)

    def _signal_attachments_dir(self) -> Path:
        """Return the directory signal-cli writes inbound attachments to.

        Defaults to ``~/.local/share/signal-cli/attachments`` (the daemon's
        platform default on Linux) when ``config.attachments_dir`` is unset.
        """
        configured = self.config.attachments_dir
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".local/share/signal-cli/attachments"

    @staticmethod
    def _normalize_signal_id(value: str) -> list[str]:
        """Normalize Signal identifiers (phone/uuid/service-id) for matching."""
        raw = value.strip()
        if not raw:
            return []

        normalized = [raw, raw.lower()]
        if raw.startswith("+") and len(raw) > 1:
            normalized.append(raw[1:])
        elif raw.isdigit():
            normalized.append(f"+{raw}")
        return list(dict.fromkeys(normalized))

    @classmethod
    def _sender_matches_allowlist(cls, sender_id: str, allow_list: list[str]) -> bool:
        """Return True if any normalized variant of sender_id is on allow_list.

        Both ``sender_id`` and each allow_list entry can be a single
        identifier or a pipe-joined composite of several (e.g.
        ``"+1234567890|uuid-abc"``); both sides are split on ``|`` and each
        part is run through ``_normalize_signal_id`` so an allowlist entry
        like ``1234567890`` matches a sender ``+1234567890`` (and vice
        versa), and case-only differences in UUIDs/ACIs match too.
        """
        if not allow_list:
            return False
        sender_variants: set[str] = set()
        for part in str(sender_id).split("|"):
            sender_variants.update(cls._normalize_signal_id(part))
        if not sender_variants:
            return False
        allow_variants: set[str] = set()
        for entry in allow_list:
            for part in str(entry).split("|"):
                allow_variants.update(cls._normalize_signal_id(part))
        return bool(sender_variants & allow_variants)

    def _remember_account_id_alias(self, value: str | None) -> None:
        """Remember known bot identifiers for mention matching."""
        if not value:
            return
        if not isinstance(value, str):
            return
        for candidate in self._normalize_signal_id(value):
            self._account_id_aliases.add(candidate)

    def _id_matches_account(self, value: str | None) -> bool:
        """Return True when an identifier refers to the bot account."""
        if not value:
            return False
        if not isinstance(value, str):
            return False
        return any(
            candidate in self._account_id_aliases for candidate in self._normalize_signal_id(value)
        )

    @staticmethod
    def _collect_sender_id_parts(envelope: dict[str, Any]) -> list[str]:
        """Collect all known sender identifier variants from an envelope."""
        parts: list[str] = []
        for key in (
            "sourceNumber",
            "source",
            "sourceUuid",
            "sourceServiceId",
            "sourceAci",
            "sourceACI",
        ):
            value = envelope.get(key)
            if not isinstance(value, str):
                continue
            candidate = value.strip()
            if candidate and candidate not in parts:
                parts.append(candidate)
        return parts

    @staticmethod
    def _primary_sender_id(sender_parts: list[str]) -> str:
        """Pick the best sender identifier for routing (prefer phone-like IDs)."""
        for part in sender_parts:
            if part.startswith("+") or part.isdigit():
                return part
        return sender_parts[0] if sender_parts else ""

    @staticmethod
    def _extract_group_id(group_info: Any, group_v2: Any) -> str | None:
        """Extract group ID from groupInfo/groupV2 payloads across signal-cli variants."""
        for group_obj in (group_info, group_v2):
            if not isinstance(group_obj, dict):
                continue
            for key in ("groupId", "id", "groupID"):
                value = group_obj.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _mention_id_candidates(mention: dict[str, Any]) -> list[str]:
        """Extract possible identifier fields from a mention payload."""
        ids: list[str] = []

        def _walk(value: dict[str, Any] | Any, depth: int = 0) -> None:
            if depth > 2:
                return
            if not isinstance(value, dict):
                return
            for key, child in value.items():
                key_lower = str(key).lower()
                if isinstance(child, str) and child:
                    if any(token in key_lower for token in ("number", "uuid", "serviceid", "aci")):
                        ids.append(child)
                elif isinstance(child, dict):
                    _walk(child, depth + 1)

        _walk(mention)
        return list(dict.fromkeys(ids))

    @staticmethod
    def _mention_span(mention: dict[str, Any]) -> tuple[int, int] | None:
        """Extract a safe (start, length) span from a mention."""
        try:
            start = int(mention.get("start", 0))
            length = int(mention.get("length", 0))
        except (TypeError, ValueError):
            return None

        if start < 0 or length <= 0:
            return None
        return (start, length)

    @staticmethod
    def _leading_placeholder_span(text: str | None) -> tuple[int, int] | None:
        """
        Detect a leading Signal mention placeholder when mention metadata is missing.

        Some clients/integrations deliver mentions as a leading placeholder character
        (typically U+FFFC) but omit `mentions` metadata in the payload.
        """
        if not text:
            return None

        start = 0
        while start < len(text) and text[start].isspace():
            start += 1

        if start >= len(text):
            return None

        marker = text[start]
        if marker not in ("\ufffc", "\ufffd", "\x1b"):
            return None

        next_index = start + 1
        if next_index < len(text) and not text[next_index].isspace():
            return None

        return (start, 1)

    def _should_respond_in_group(self, message_text: str, mentions: list[dict[str, Any]]) -> bool:
        """
        Determine if the bot should respond to a group message.

        Args:
            message_text: The message text content
            mentions: List of mentions from Signal (format: [{"number": "+1234567890", "start": 0, "length": 10}])

        Returns:
            True if bot should respond, False otherwise
        """
        # Group reply behavior is controlled only by group.require_mention.
        if not self.config.group.require_mention:
            return True

        # If mention is required, check if bot was mentioned.
        for mention in mentions:
            if not isinstance(mention, dict):
                continue
            for mention_id in self._mention_id_candidates(mention):
                if self._id_matches_account(mention_id):
                    return True

        # Some Signal clients emit mention spans without recipient identifiers
        # (for handle-style mentions). Accept a leading identifier-less mention
        # as a mention of the bot to avoid false negatives.
        for mention in mentions:
            if not isinstance(mention, dict):
                continue
            if self._mention_id_candidates(mention):
                continue
            span = self._mention_span(mention)
            if not span:
                continue
            start, _ = span
            if message_text is not None and not message_text[:start].strip():
                self.logger.debug("Accepting identifier-less leading mention as bot mention")
                return True

        # Some payloads omit `mentions` but still include the leading mention
        # placeholder character in the message body.
        if not mentions and self._leading_placeholder_span(message_text):
            self.logger.debug("Accepting leading placeholder mention without mention metadata")
            return True

        # Fallback: check for configured phone number in plain text.
        if message_text and self.config.phone_number:
            for account_id in self._normalize_signal_id(self.config.phone_number):
                if account_id and account_id in message_text:
                    return True

        return False

    def _strip_bot_mention(self, text: str, mentions: list[dict[str, Any]]) -> str:
        """
        Remove bot mentions from message text.

        Signal mentions are embedded in the text, so we need to remove them based on
        the mentions array which provides start position and length.

        Args:
            text: Original message text
            mentions: List of mention objects with start/length positions

        Returns:
            Text with bot mentions removed
        """
        if not text:
            return text

        # Build a list of (start, length) tuples for our bot's mentions
        bot_mentions = []
        for mention in mentions:
            if not isinstance(mention, dict):
                continue
            mention_ids = self._mention_id_candidates(mention)
            span = self._mention_span(mention)
            if not span:
                continue

            # Strip matched bot mentions by ID.
            if any(self._id_matches_account(mention_id) for mention_id in mention_ids):
                bot_mentions.append(span)
                continue

            # Also strip identifier-less leading mention spans (handle mentions).
            if not mention_ids:
                start, _ = span
                if not text[:start].strip():
                    bot_mentions.append(span)

        if not bot_mentions:
            placeholder_span = self._leading_placeholder_span(text)
            if placeholder_span:
                bot_mentions.append(placeholder_span)

        # Sort mentions by start position (descending) to remove from end to start
        # This prevents position shifts when removing earlier mentions
        bot_mentions.sort(reverse=True)

        # Remove each mention
        for start, length in bot_mentions:
            if start >= len(text):
                continue
            end = min(len(text), start + length)
            text = text[:start] + text[end:]

        return text.strip()

    @staticmethod
    def _is_group_chat_id(chat_id: str) -> bool:
        """Return True when chat_id appears to be a Signal group ID (base64)."""
        return "=" in chat_id or (len(chat_id) > 40 and "-" not in chat_id)

    def _recipient_params(self, chat_id: str) -> dict[str, Any]:
        """Build recipient params for signal-cli JSON-RPC methods."""
        if self._is_group_chat_id(chat_id):
            return {"groupId": chat_id}
        return {"recipient": [chat_id]}

    async def _start_typing(self, chat_id: str) -> None:
        """Start periodic typing indicator updates for a chat."""
        await self._stop_typing(chat_id, send_stop=False)
        await self._send_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    async def _stop_typing(self, chat_id: str, send_stop: bool = True) -> None:
        """Stop typing indicator updates for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        had_task = task is not None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if send_stop and had_task:
            await self._send_typing(chat_id, stop=True)

    async def _typing_loop(self, chat_id: str) -> None:
        """Send typing updates periodically until cancelled."""
        try:
            while self._running:
                await asyncio.sleep(self._TYPING_REFRESH_SECONDS)
                await self._send_typing(chat_id, quiet_success=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.debug("Typing indicator loop stopped for {}: {}", chat_id, e)

    async def _send_typing(
        self, chat_id: str, stop: bool = False, quiet_success: bool = False
    ) -> None:
        """Send a typing START/STOP message via signal-cli."""
        action = "stop" if stop else "start"
        if (
            not self._is_group_chat_id(chat_id)
            and chat_id.startswith("+") is False
            and chat_id not in self._typing_uuid_warnings
        ):
            self._typing_uuid_warnings.add(chat_id)
            self.logger.warning(
                "Signal DM recipient is UUID-only (no phone number in envelope). "
                "Some Signal clients may not render typing indicators for this recipient form."
            )
        candidate_params: list[dict[str, Any]]
        if self._is_group_chat_id(chat_id):
            candidate_params = [{"groupId": chat_id}, {"groupId": [chat_id]}]
        else:
            candidate_params = [{"recipient": chat_id}, {"recipient": [chat_id]}]

        last_error: Any | None = None
        for params in candidate_params:
            if stop:
                params["stop"] = True
            try:
                response = await self._send_request("sendTyping", params)
            except Exception as e:
                last_error = str(e)
                continue

            if "error" not in response:
                if not quiet_success:
                    self.logger.info("Signal typing {} sent for {}", action, chat_id)
                return

            last_error = response["error"]

        self.logger.warning(
            "Failed to send Signal typing {} for {}: {}", action, chat_id, last_error
        )

    async def _ensure_typing_indicators_enabled(self) -> None:
        """Enable typing indicators on the bot account."""
        response = await self._send_request("updateConfiguration", {"typingIndicators": True})
        if "error" in response:
            self.logger.warning(
                "Failed to enable Signal typing indicators: {}", response["error"]
            )
        else:
            self.logger.info("Signal typing indicators enabled on account configuration")

    async def _send_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a JSON-RPC request via HTTP and wait for response."""
        # Generate request ID
        self._request_id += 1
        request_id = self._request_id

        # Build JSON-RPC request
        request = {"jsonrpc": "2.0", "method": method, "id": request_id}

        if params:
            request["params"] = params

        return await self._send_http_request(request)

    async def _send_http_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send JSON-RPC request via HTTP."""
        if not self._http:
            raise RuntimeError("Not connected to signal-cli daemon")

        try:
            response = await self._http.post("/api/v1/rpc", json=request)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error("HTTP request failed: {}", e)
            return {"error": {"message": str(e)}}
