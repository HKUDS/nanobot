"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    ProgressEvent,
    RetryWaitEvent,
    RuntimeModelUpdatedEvent,
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_event_from_message,
    replace_outbound_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config
from nanobot.utils.restart import consume_restart_notice_from_env, format_restart_completed_message

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


def _default_webui_dist() -> Path | None:
    """Return the absolute path to the bundled webui dist directory if it exists."""
    try:
        import nanobot.web as web_pkg  # type: ignore[import-not-found]
    except ImportError:
        return None
    candidate = Path(web_pkg.__file__).resolve().parent / "dist"
    return candidate if candidate.is_dir() else None


# Retry delays for message sending (exponential backoff: 1s, 2s, 4s)
_SEND_RETRY_DELAYS = (1, 2, 4)

_BOOL_CAMEL_ALIASES: dict[str, str] = {
    "send_progress": "sendProgress",
    "send_tool_hints": "sendToolHints",
    "show_reasoning": "showReasoning",
}

class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages
    """

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        *,
        session_manager: "SessionManager | None" = None,
        cron_service: Any | None = None,
        webui_runtime_model_name: Callable[[], str | None] | None = None,
        webui_cron_pending_job_ids: Callable[[str], set[str]] | None = None,
        webui_static_dist: bool = True,
        webui_runtime_surface: str = "browser",
        webui_runtime_capabilities: dict[str, Any] | None = None,
    ):
        self.config = config
        self.bus = bus
        self._session_manager = session_manager
        self._cron_service = cron_service
        self._webui_runtime_model_name = webui_runtime_model_name
        self._webui_cron_pending_job_ids = webui_cron_pending_job_ids
        self._webui_static_dist = webui_static_dist
        self._webui_runtime_surface = webui_runtime_surface
        self._webui_runtime_capabilities = dict(webui_runtime_capabilities or {})
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._origin_reply_fingerprints: dict[tuple[str, str, str], str] = {}

        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels discovered via pkgutil scan + entry_points plugins."""
        from nanobot.channels.registry import discover_channel_names, discover_enabled

        # Collect enabled module names first, then only import those.
        # Channel configs live in ChannelsConfig's extra fields (via
        # extra="allow"), so we enumerate candidates from pkgutil scan
        # (cheap, no imports) and any plugin keys in __pydantic_extra__.
        names = discover_channel_names()
        candidate_names = set(names)
        extra = getattr(self.config.channels, "__pydantic_extra__", None) or {}
        candidate_names.update(extra.keys())

        enabled_names: set[str] = set()
        for name in candidate_names:
            section = getattr(self.config.channels, name, None)
            if section is None:
                continue
            if (
                section.get("enabled", False)
                if isinstance(section, dict)
                else getattr(section, "enabled", False)
            ):
                enabled_names.add(name)

        for name, cls in discover_enabled(enabled_names, _names=names).items():
            section = getattr(self.config.channels, name, None)
            if section is None:
                continue
            try:
                kwargs: dict[str, Any] = {}
                if cls.name == "websocket":
                    from nanobot.channels.websocket import WebSocketConfig
                    from nanobot.webui.gateway_services import build_gateway_services

                    parsed = WebSocketConfig.model_validate(section)
                    static_path = _default_webui_dist() if self._webui_static_dist else None
                    workspace = Path(self.config.workspace_path)
                    gateway = build_gateway_services(
                        config=parsed,
                        bus=self.bus,
                        session_manager=self._session_manager,
                        static_dist_path=static_path,
                        workspace_path=workspace,
                        default_restrict_to_workspace=self.config.tools.restrict_to_workspace,
                        disabled_skills=set(self.config.agents.defaults.disabled_skills),
                        runtime_model_name=self._webui_runtime_model_name,
                        runtime_surface=self._webui_runtime_surface,
                        runtime_capabilities_overrides=self._webui_runtime_capabilities,
                        cron_service=self._cron_service,
                        cron_pending_job_ids=self._webui_cron_pending_job_ids,
                        logger=logger,
                    )
                    kwargs["gateway"] = gateway
                channel = cls(section, self.bus, **kwargs)
                channel.send_progress = self._resolve_bool_override(
                    section, "send_progress", self.config.channels.send_progress,
                )
                channel.send_tool_hints = self._resolve_bool_override(
                    section, "send_tool_hints", self.config.channels.send_tool_hints,
                )
                channel.show_reasoning = self._resolve_bool_override(
                    section, "show_reasoning", self.config.channels.show_reasoning,
                )
                self.channels[name] = channel
                logger.info("{} channel enabled", cls.display_name)
            except Exception as e:
                logger.warning("{} channel not available: {}", name, e)

        self._validate_allow_from()

    def _validate_allow_from(self) -> None:
        for name, ch in self.channels.items():
            cfg = ch.config
            if isinstance(cfg, dict):
                if "allow_from" in cfg:
                    allow = cfg.get("allow_from")
                else:
                    allow = cfg.get("allowFrom")
            else:
                allow = getattr(cfg, "allow_from", None)
            if allow is None:
                # allowFrom omitted → pairing-only mode.  Unapproved senders
                # receive a pairing code instead of being silently ignored.
                logger.info(
                    '"{}" has no allowFrom; unapproved users will receive a pairing code',
                    name,
                )

    def _should_send_progress(self, channel_name: str, *, tool_hint: bool = False) -> bool:
        """Return whether progress (or tool-hints) may be sent to *channel_name*."""
        ch = self.channels.get(channel_name)
        if ch is None:
            logger.debug("Progress check for unknown channel: {}", channel_name)
            return False
        return ch.send_tool_hints if tool_hint else ch.send_progress

    def _resolve_bool_override(self, section: Any, key: str, default: bool) -> bool:
        """Return *key* from *section* if it is a bool, otherwise *default*.

        For dict configs also checks the camelCase alias (e.g. ``sendProgress``
        for ``send_progress``) so raw JSON/TOML configs work alongside
        Pydantic models.
        """
        if isinstance(section, dict):
            value = section.get(key)
            if value is None:
                camel = _BOOL_CAMEL_ALIASES.get(key)
                if camel:
                    value = section.get(camel)
            return value if isinstance(value, bool) else default
        value = getattr(section, key, None)
        return value if isinstance(value, bool) else default

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception:
            logger.exception("Failed to start channel {}", name)

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            logger.info("Starting {} channel...", name)
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        self._notify_restart_done_if_needed()

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)

    def _notify_restart_done_if_needed(self) -> None:
        """Send restart completion message when runtime env markers are present."""
        notice = consume_restart_notice_from_env()
        if not notice:
            return
        target = self.channels.get(notice.channel)
        if not target:
            return
        asyncio.create_task(self._send_with_retry(
            target,
            OutboundMessage(
                channel=notice.channel,
                chat_id=notice.chat_id,
                content=format_restart_completed_message(notice.started_at_raw),
                metadata=dict(notice.metadata or {}),
            ),
        ))

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")

        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._dispatch_task

        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Stopped {} channel", name)
            except asyncio.CancelledError:
                if asyncio.current_task() and asyncio.current_task().cancelling():
                    raise
                logger.debug("Channel {} stop task was already cancelled", name)
            except Exception:
                logger.exception("Error stopping {}", name)

    @staticmethod
    def _fingerprint_content(content: str) -> str:
        normalized = " ".join(content.split())
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest() if normalized else ""

    def _should_suppress_outbound(self, msg: OutboundMessage) -> bool:
        metadata = msg.metadata or {}
        if isinstance(outbound_event_from_message(msg), ProgressEvent):
            return False
        fingerprint = self._fingerprint_content(msg.content)
        if not fingerprint:
            return False

        origin_message_id = metadata.get("origin_message_id")
        if isinstance(origin_message_id, str) and origin_message_id:
            key = (msg.channel, msg.chat_id, origin_message_id)
            if self._origin_reply_fingerprints.get(key) == fingerprint:
                return True
            self._origin_reply_fingerprints[key] = fingerprint

        message_id = metadata.get("message_id")
        if isinstance(message_id, str) and message_id:
            key = (msg.channel, msg.chat_id, message_id)
            self._origin_reply_fingerprints[key] = fingerprint

        return False

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        # Buffer for messages that couldn't be processed during delta coalescing
        # (since asyncio.Queue doesn't support push_front)
        pending: list[OutboundMessage] = []

        while True:
            try:
                # First check pending buffer before waiting on queue
                if pending:
                    msg = pending.pop(0)
                else:
                    msg = await asyncio.wait_for(
                        self.bus.consume_outbound(),
                        timeout=1.0
                    )

                event = outbound_event_from_message(msg)
                progress_event = event if isinstance(event, ProgressEvent) else None
                if progress_event and (
                    progress_event.reasoning_delta
                    or progress_event.reasoning_end
                    or progress_event.reasoning
                ):
                    # Reasoning rides its own plugin channel: only delivered
                    # when the destination channel opts in via ``show_reasoning``
                    # and overrides the streaming primitives. Channels without
                    # a low-emphasis UI affordance keep the base no-op and the
                    # content silently drops here.
                    channel = self.channels.get(msg.channel)
                    if channel is not None and channel.show_reasoning:
                        await self._send_with_retry(channel, msg)
                    continue

                if progress_event:
                    if progress_event.tool_hint and not self._should_send_progress(
                        msg.channel, tool_hint=True,
                    ):
                        continue
                    if not progress_event.tool_hint and not self._should_send_progress(
                        msg.channel, tool_hint=False,
                    ):
                        continue

                if isinstance(event, RetryWaitEvent):
                    continue

                if (
                    isinstance(event, RuntimeModelUpdatedEvent)
                    and msg.channel == "websocket"
                    and "websocket" not in self.channels
                ):
                    continue

                # Coalesce consecutive stream delta messages for the same (channel, chat_id)
                # to reduce API calls and improve streaming latency
                if isinstance(event, StreamDeltaEvent):
                    msg, extra_pending = self._coalesce_stream_deltas(msg)
                    pending.extend(extra_pending)
                    event = outbound_event_from_message(msg)

                channel = self.channels.get(msg.channel)
                if channel:
                    # Duplicate suppression is scoped to a known source message
                    # so repeated content from separate turns is still delivered.
                    if (
                        not isinstance(
                            event,
                            StreamDeltaEvent | StreamEndEvent | StreamedResponseEvent,
                        )
                    ):
                        if self._should_suppress_outbound(msg):
                            logger.info("Suppressing duplicate outbound message to {}:{}", msg.channel, msg.chat_id)
                            continue
                    await self._send_with_retry(channel, msg)
                else:
                    logger.warning("Unknown channel: {}", msg.channel)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    @staticmethod
    def _accepts_keyword(callable_obj: Callable[..., Any], name: str) -> bool:
        try:
            signature = inspect.signature(callable_obj)
        except (TypeError, ValueError):
            return True
        return any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD or parameter.name == name
            for parameter in signature.parameters.values()
        )

    @classmethod
    async def _send_reasoning_delta(cls, channel: BaseChannel, msg: OutboundMessage, event: ProgressEvent) -> None:
        metadata = msg.metadata
        kwargs: dict[str, Any] = {}
        if cls._accepts_keyword(channel.send_reasoning_delta, "stream_id"):
            kwargs["stream_id"] = event.stream_id
        else:
            metadata = dict(metadata or {})
            metadata["_reasoning_delta"] = True
            if event.stream_id is not None:
                metadata["_stream_id"] = event.stream_id
        await channel.send_reasoning_delta(
            msg.chat_id,
            msg.content,
            metadata,
            **kwargs,
        )

    @classmethod
    async def _send_reasoning_end(cls, channel: BaseChannel, msg: OutboundMessage, event: ProgressEvent) -> None:
        metadata = msg.metadata
        kwargs: dict[str, Any] = {}
        if cls._accepts_keyword(channel.send_reasoning_end, "stream_id"):
            kwargs["stream_id"] = event.stream_id
        else:
            metadata = dict(metadata or {})
            metadata["_reasoning_end"] = True
            if event.stream_id is not None:
                metadata["_stream_id"] = event.stream_id
        await channel.send_reasoning_end(
            msg.chat_id,
            metadata,
            **kwargs,
        )

    @classmethod
    async def _send_stream_event(
        cls,
        channel: BaseChannel,
        msg: OutboundMessage,
        event: StreamDeltaEvent | StreamEndEvent,
    ) -> None:
        metadata = msg.metadata
        kwargs: dict[str, Any] = {}
        if cls._accepts_keyword(channel.send_delta, "stream_id"):
            kwargs["stream_id"] = event.stream_id
        else:
            metadata = dict(metadata or {})
            if event.stream_id is not None:
                metadata["_stream_id"] = event.stream_id

        if isinstance(event, StreamEndEvent):
            if cls._accepts_keyword(channel.send_delta, "stream_end"):
                kwargs["stream_end"] = True
            else:
                metadata = dict(metadata or {})
                metadata["_stream_end"] = True
            if cls._accepts_keyword(channel.send_delta, "resuming"):
                kwargs["resuming"] = event.resuming
        elif not kwargs:
            metadata = dict(metadata or {})
            metadata["_stream_delta"] = True

        await channel.send_delta(
            msg.chat_id,
            msg.content,
            metadata,
            **kwargs,
        )

    @staticmethod
    async def _send_once(channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send one outbound message without retry policy."""
        event = outbound_event_from_message(msg)
        if isinstance(event, ProgressEvent) and event.reasoning_end:
            await ChannelManager._send_reasoning_end(channel, msg, event)
        elif isinstance(event, ProgressEvent) and event.reasoning_delta:
            await ChannelManager._send_reasoning_delta(channel, msg, event)
        elif isinstance(event, ProgressEvent) and event.reasoning:
            # BaseChannel translates one-shot reasoning to a single delta +
            # end pair so plugins only implement the streaming primitives.
            await channel.send_reasoning(msg)
        elif isinstance(event, ProgressEvent) and event.file_edit_events:
            await channel.send_file_edit_events(
                msg.chat_id,
                event.file_edit_events,
                msg.metadata,
            )
        elif isinstance(event, StreamDeltaEvent):
            await ChannelManager._send_stream_event(channel, msg, event)
        elif isinstance(event, StreamEndEvent):
            await ChannelManager._send_stream_event(channel, msg, event)
        elif not isinstance(event, StreamedResponseEvent):
            await channel.send(msg)

    def _coalesce_stream_deltas(
        self, first_msg: OutboundMessage
    ) -> tuple[OutboundMessage, list[OutboundMessage]]:
        """Merge consecutive stream deltas for the same (channel, chat_id, stream_id).

        This reduces the number of API calls when the queue has accumulated multiple
        deltas, which happens when LLM generates faster than the channel can process.

        Returns:
            tuple of (merged_message, list_of_non_matching_messages)
        """
        first_event = outbound_event_from_message(first_msg)
        first_stream_id = first_event.stream_id if isinstance(first_event, StreamDeltaEvent) else None
        target_key = (first_msg.channel, first_msg.chat_id, first_stream_id)
        combined_content = first_msg.content
        final_event: StreamDeltaEvent | StreamEndEvent = (
            first_event
            if isinstance(first_event, StreamDeltaEvent)
            else StreamDeltaEvent(stream_id=first_stream_id)
        )
        non_matching: list[OutboundMessage] = []

        # Only merge consecutive deltas. As soon as we hit any other message,
        # stop and hand that boundary back to the dispatcher via `pending`.
        while True:
            try:
                next_msg = self.bus.outbound.get_nowait()
            except asyncio.QueueEmpty:
                break

            # Check if this message belongs to the same stream
            next_event = outbound_event_from_message(next_msg)
            next_stream_id = (
                next_event.stream_id
                if isinstance(next_event, StreamDeltaEvent | StreamEndEvent)
                else None
            )
            same_target = (
                next_msg.channel,
                next_msg.chat_id,
                next_stream_id,
            ) == target_key
            is_delta = isinstance(next_event, StreamDeltaEvent)
            is_end = isinstance(next_event, StreamEndEvent)

            if same_target and (is_delta or (is_end and next_msg.content)):
                # Accumulate content
                combined_content += next_msg.content
                # If we see stream_end, remember it and stop coalescing this stream
                if isinstance(next_event, StreamEndEvent):
                    final_event = StreamEndEvent(
                        stream_id=next_stream_id,
                        resuming=next_event.resuming,
                    )
                    # Stream ended - stop coalescing this stream
                    break
            else:
                # First non-matching message defines the coalescing boundary.
                non_matching.append(next_msg)
                break

        merged = replace_outbound_event(first_msg, final_event, content=combined_content)
        return merged, non_matching

    async def _send_with_retry(self, channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send a message with retry on failure using exponential backoff.

        Note: CancelledError is re-raised to allow graceful shutdown.
        """
        max_attempts = max(self.config.channels.send_max_retries, 1)

        for attempt in range(max_attempts):
            try:
                await self._send_once(channel, msg)
                return  # Send succeeded
            except asyncio.CancelledError:
                raise  # Propagate cancellation for graceful shutdown
            except Exception as e:
                if attempt == max_attempts - 1:
                    logger.exception(
                        "Failed to send to {} after {} attempts",
                        msg.channel, max_attempts
                    )
                    return
                delay = _SEND_RETRY_DELAYS[min(attempt, len(_SEND_RETRY_DELAYS) - 1)]
                logger.warning(
                    "Send to {} failed (attempt {}/{}): {}, retrying in {}s",
                    msg.channel, attempt + 1, max_attempts, type(e).__name__, delay
                )
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    raise  # Propagate cancellation during sleep

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running
            }
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
