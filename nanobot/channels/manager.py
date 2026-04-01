"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config

# Retry delays for message sending (exponential backoff: 1s, 2s, 4s)
_SEND_RETRY_DELAYS = (1, 2, 4)

# Interval between full cache sweeps (seconds)
_CLEANUP_INTERVAL_S = 60


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages
    """

    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._channel_queues: dict[str, asyncio.Queue[tuple[BaseChannel, OutboundMessage]]] = {}
        self._channel_workers: dict[str, asyncio.Task] = {}
        # Spam guard: tracks (channel, chat_id, content_hash) → [timestamps]
        self._dedup_log: dict[tuple[str, str, str], list[float]] = {}
        self._dedup_last_cleanup: float = 0.0

        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels discovered via pkgutil scan + entry_points plugins."""
        from nanobot.channels.registry import discover_all

        groq_key = self.config.providers.groq.api_key

        for name, cls in discover_all().items():
            section = getattr(self.config.channels, name, None)
            if section is None:
                continue
            enabled = (
                section.get("enabled", False)
                if isinstance(section, dict)
                else getattr(section, "enabled", False)
            )
            if not enabled:
                continue
            try:
                channel = cls(section, self.bus)
                channel.transcription_api_key = groq_key
                self.channels[name] = channel
                logger.info("{} channel enabled", cls.display_name)
            except Exception as e:
                logger.warning("{} channel not available: {}", name, e)

        self._validate_allow_from()

    def _validate_allow_from(self) -> None:
        for name, ch in self.channels.items():
            if getattr(ch.config, "allow_from", None) == []:
                raise SystemExit(
                    f'Error: "{name}" has empty allowFrom (denies all). '
                    f'Set ["*"] to allow everyone, or add specific user IDs.'
                )

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error("Failed to start channel {}: {}", name, e)

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

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")

        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Stop per-channel workers
        for name, task in self._channel_workers.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._channel_workers.clear()
        self._channel_queues.clear()

        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Stopped {} channel", name)
            except Exception as e:
                logger.error("Error stopping {}: {}", name, e)

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

                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not self.config.channels.send_tool_hints:
                        if msg._delivery_future and not msg._delivery_future.done():
                            msg._delivery_future.set_result(None)
                        continue
                    if not msg.metadata.get("_tool_hint") and not self.config.channels.send_progress:
                        if msg._delivery_future and not msg._delivery_future.done():
                            msg._delivery_future.set_result(None)
                        continue

                # Coalesce consecutive _stream_delta messages for the same (channel, chat_id)
                # to reduce API calls and improve streaming latency
                if msg.metadata.get("_stream_delta") and not msg.metadata.get("_stream_end"):
                    msg, extra_pending = self._coalesce_stream_deltas(msg)
                    pending.extend(extra_pending)

                # Spam guard: suppress near-identical messages to the same recipient
                if self.config.channels.spam_guard.enabled and self._is_spam(msg):
                    logger.warning(
                        "Spam guard: suppressed duplicate message to {}:{}",
                        msg.channel, msg.chat_id,
                    )
                    if msg._delivery_future and not msg._delivery_future.done():
                        msg._delivery_future.set_result(None)
                    continue

                channel = self.channels.get(msg.channel)
                if channel:
                    await self._enqueue_channel_send(msg.channel, channel, msg)
                else:
                    logger.warning("Unknown channel: {}", msg.channel)
                    if msg._delivery_future and not msg._delivery_future.done():
                        msg._delivery_future.set_exception(
                            ValueError(f"Unknown channel: {msg.channel}")
                        )

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def _is_spam(self, msg: OutboundMessage) -> bool:
        """Check if a message is a near-duplicate sent too many times recently.

        Streaming deltas and progress messages are exempt.
        """
        meta = msg.metadata or {}
        if meta.get("_stream_delta") or meta.get("_stream_end") or meta.get("_progress"):
            return False
        if not isinstance(msg.content, str) or not msg.content.strip():
            return False

        sg = self.config.channels.spam_guard
        content_hash = hashlib.sha256(
            msg.content.strip().encode("utf-8", errors="replace")
        ).hexdigest()[:12]
        key = (msg.channel, msg.chat_id or "", content_hash)
        now = time.monotonic()

        # Prune expired entries for this key
        if key in self._dedup_log:
            self._dedup_log[key] = [
                t for t in self._dedup_log[key] if now - t < sg.window_s
            ]
            if not self._dedup_log[key]:
                del self._dedup_log[key]

        # Periodic full cache sweep (time-based, not per-message)
        if now - self._dedup_last_cleanup > _CLEANUP_INTERVAL_S:
            self._dedup_last_cleanup = now
            expired = [
                k for k, v in self._dedup_log.items()
                if not v or now - v[-1] >= sg.window_s
            ]
            for k in expired:
                del self._dedup_log[k]

        timestamps = self._dedup_log.get(key, [])
        if len(timestamps) >= sg.max_repeats:
            return True

        self._dedup_log.setdefault(key, []).append(now)
        return False

    async def _enqueue_channel_send(
        self, channel_name: str, channel: BaseChannel, msg: OutboundMessage
    ) -> None:
        """Enqueue a message for per-channel delivery (non-blocking for other channels)."""
        if channel_name not in self._channel_queues:
            q: asyncio.Queue[tuple[BaseChannel, OutboundMessage]] = asyncio.Queue()
            self._channel_queues[channel_name] = q
            self._channel_workers[channel_name] = asyncio.create_task(
                self._channel_worker(channel_name, q)
            )
        await self._channel_queues[channel_name].put((channel, msg))

    async def _channel_worker(
        self, name: str, q: asyncio.Queue[tuple[BaseChannel, OutboundMessage]]
    ) -> None:
        """Process outbound messages for a single channel, preserving order."""
        while True:
            try:
                channel, msg = await q.get()
                await self._send_with_retry(channel, msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Channel worker {} error: {}", name, e)

    @staticmethod
    async def _send_once(channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send one outbound message without retry policy."""
        if msg.metadata.get("_stream_delta") or msg.metadata.get("_stream_end"):
            await channel.send_delta(msg.chat_id, msg.content, msg.metadata)
        elif not msg.metadata.get("_streamed"):
            await channel.send(msg)

    def _coalesce_stream_deltas(
        self, first_msg: OutboundMessage
    ) -> tuple[OutboundMessage, list[OutboundMessage]]:
        """Merge consecutive _stream_delta messages for the same (channel, chat_id).

        This reduces the number of API calls when the queue has accumulated multiple
        deltas, which happens when LLM generates faster than the channel can process.

        Returns:
            tuple of (merged_message, list_of_non_matching_messages)
        """
        target_key = (first_msg.channel, first_msg.chat_id)
        combined_content = first_msg.content
        final_metadata = dict(first_msg.metadata or {})
        non_matching: list[OutboundMessage] = []

        # Only merge consecutive deltas. As soon as we hit any other message,
        # stop and hand that boundary back to the dispatcher via `pending`.
        while True:
            try:
                next_msg = self.bus.outbound.get_nowait()
            except asyncio.QueueEmpty:
                break

            # Check if this message belongs to the same stream
            same_target = (next_msg.channel, next_msg.chat_id) == target_key
            is_delta = next_msg.metadata and next_msg.metadata.get("_stream_delta")
            is_end = next_msg.metadata and next_msg.metadata.get("_stream_end")

            if same_target and is_delta and not final_metadata.get("_stream_end"):
                # Accumulate content
                combined_content += next_msg.content
                # Resolve consumed message's delivery future (content merged into first_msg)
                if next_msg._delivery_future and not next_msg._delivery_future.done():
                    next_msg._delivery_future.set_result(None)
                # If we see _stream_end, remember it and stop coalescing this stream
                if is_end:
                    final_metadata["_stream_end"] = True
                    # Stream ended - stop coalescing this stream
                    break
            else:
                # First non-matching message defines the coalescing boundary.
                non_matching.append(next_msg)
                break

        merged = OutboundMessage(
            channel=first_msg.channel,
            chat_id=first_msg.chat_id,
            content=combined_content,
            metadata=final_metadata,
        )
        return merged, non_matching

    async def _send_with_retry(self, channel: BaseChannel, msg: OutboundMessage) -> None:
        """Send a message with retry on failure using exponential backoff.

        Note: CancelledError is re-raised to allow graceful shutdown.
        """
        max_attempts = max(self.config.channels.send_max_retries, 1)
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                await self._send_once(channel, msg)
                if msg._delivery_future and not msg._delivery_future.done():
                    msg._delivery_future.set_result(None)
                return  # Send succeeded
            except asyncio.CancelledError:
                raise  # Propagate cancellation for graceful shutdown
            except Exception as e:
                last_error = e
                if attempt == max_attempts - 1:
                    logger.error(
                        "Failed to send to {} after {} attempts: {} - {}",
                        msg.channel, max_attempts, type(e).__name__, e
                    )
                    if msg._delivery_future and not msg._delivery_future.done():
                        msg._delivery_future.set_exception(e)
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
