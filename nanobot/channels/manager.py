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
from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import (
    ChannelActivation,
    channel_instance_specs,
    channel_runtime_name,
    external_channel_enabled,
)
from nanobot.channels.registry import DEFAULT_ENABLED_CHANNELS
from nanobot.config.schema import Config
from nanobot.utils.restart import (
    RestartNotice,
    consume_restart_notice_from_env,
    format_restart_completed_message,
)

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
_RESTART_NOTICE_START_TIMEOUT_S = 30.0
_RESTART_NOTICE_START_POLL_S = 0.25

_BOOL_CAMEL_ALIASES: dict[str, str] = {
    "send_progress": "sendProgress",
    "send_tool_hints": "sendToolHints",
    "show_reasoning": "showReasoning",
}

def _default_channel_config(name: str) -> dict[str, Any] | None:
    if name != "websocket":
        return None
    from nanobot.channels.websocket import WebSocketChannel

    return WebSocketChannel.default_config()


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
        local_trigger_store: Any | None = None,
        webui_runtime_model_name: Callable[[], str | None] | None = None,
        webui_cron_pending_job_ids: Callable[[str], set[str]] | None = None,
        webui_local_trigger_pending_ids: Callable[[str], set[str]] | None = None,
        webui_static_dist: bool = True,
        webui_runtime_surface: str = "browser",
        webui_runtime_capabilities: dict[str, Any] | None = None,
    ):
        self.config = config
        self.bus = bus
        self._session_manager = session_manager
        self._cron_service = cron_service
        self._local_trigger_store = local_trigger_store
        self._webui_runtime_model_name = webui_runtime_model_name
        self._webui_cron_pending_job_ids = webui_cron_pending_job_ids
        self._webui_local_trigger_pending_ids = webui_local_trigger_pending_ids
        self._webui_static_dist = webui_static_dist
        self._webui_runtime_surface = webui_runtime_surface
        self._webui_runtime_capabilities = dict(webui_runtime_capabilities or {})
        self.channels: dict[str, BaseChannel] = {}
        self._channel_owners: dict[str, str] = {}
        self._channel_tasks: dict[str, asyncio.Task] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._started = False
        self._origin_reply_fingerprints: dict[tuple[str, str, str], str] = {}

        self._init_channels()

    def _config_extra_channel_names(self, config: Config | None = None) -> set[str]:
        extra = getattr((config or self.config).channels, "__pydantic_extra__", None) or {}
        return set(extra.keys())

    def _channel_section(
        self,
        name: str,
        *,
        config: Config | None = None,
        default_sections: dict[str, Any] | None = None,
    ) -> Any:
        config = config or self.config
        section = getattr(config.channels, name, None)
        if section is not None or name not in DEFAULT_ENABLED_CHANNELS:
            return section
        if default_sections is None:
            return _default_channel_config(name)
        if name not in default_sections:
            default = _default_channel_config(name)
            if default is not None:
                default_sections[name] = default
        return default_sections.get(name)

    def _build_channel(
        self,
        name: str,
        cls: type[BaseChannel],
        section: Any,
        *,
        runtime_name: str | None = None,
    ) -> BaseChannel:
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
                local_trigger_store=self._local_trigger_store,
                cron_pending_job_ids=self._webui_cron_pending_job_ids,
                local_trigger_pending_ids=self._webui_local_trigger_pending_ids,
                channel_feature_action=self.apply_channel_feature_action,
                logger=logger,
            )
            kwargs["gateway"] = gateway
        channel = cls(section, self.bus, **kwargs)
        if runtime_name and runtime_name != channel.name:
            channel.name = runtime_name
        channel.send_progress = self._resolve_bool_override(
            section, "send_progress", self.config.channels.send_progress,
        )
        channel.send_tool_hints = self._resolve_bool_override(
            section, "send_tool_hints", self.config.channels.send_tool_hints,
        )
        channel.show_reasoning = self._resolve_bool_override(
            section, "show_reasoning", self.config.channels.show_reasoning,
        )
        return channel

    def _init_channels(self) -> None:
        """Initialize channels discovered via pkgutil scan + entry_points plugins."""
        from nanobot.channels.registry import discover_channel_names, discover_enabled

        # Built-ins remain lazy: only dependency-free manifests may opt into
        # instance-aware activation before their runtime module is imported.
        # External plugins use the top-level enabled flag as their import gate;
        # once loaded, instance_specs() owns any finer-grained activation.
        names = discover_channel_names()
        builtin_names = set(names)
        default_sections: dict[str, Any] = {}

        enabled_names: set[str] = set()
        for name in self._config_extra_channel_names() - builtin_names:
            section = self._channel_section(name)
            if external_channel_enabled(section):
                enabled_names.add(name)
        for name in builtin_names:
            section = self._channel_section(name, default_sections=default_sections)
            if section is None:
                continue
            setup_spec = channel_setup_spec(name)
            activation = ChannelActivation.from_config(
                section,
                include_instances=bool(setup_spec and setup_spec.multi_instance),
            )
            if activation.resolve(default=name in DEFAULT_ENABLED_CHANNELS):
                enabled_names.add(name)

        for name, cls in discover_enabled(
            enabled_names,
            _names=names,
            warn_import_errors=True,
        ).items():
            section = self._channel_section(name, default_sections=default_sections)
            if section is None:
                continue
            try:
                specs = channel_instance_specs(cls, section)
                runtime_specs = [
                    (channel_runtime_name(cls, spec.instance_id), spec)
                    for spec in specs
                ]
                collisions = sorted(
                    set(self.channels) & {runtime_name for runtime_name, _ in runtime_specs}
                )
                if collisions:
                    raise ValueError(
                        f"runtime name(s) already owned by another channel: {', '.join(collisions)}"
                    )
                built = [
                    (
                        runtime_name,
                        self._build_channel(
                            name,
                            cls,
                            spec.config,
                            runtime_name=runtime_name,
                        ),
                    )
                    for runtime_name, spec in runtime_specs
                ]
                for runtime_name, channel in built:
                    self.channels[runtime_name] = channel
                    self._channel_owners[runtime_name] = name
                    logger.info("{} channel enabled as {}", cls.display_name, runtime_name)
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

    def _start_channel_task(self, name: str, channel: BaseChannel) -> asyncio.Task:
        logger.info("Starting {} channel...", name)
        task = asyncio.create_task(self._start_channel(name, channel))
        self._channel_tasks[name] = task
        return task

    async def _stop_channel(self, name: str) -> bool:
        channel = self.channels.get(name)
        if channel is None:
            self._channel_tasks.pop(name, None)
            return False

        task = self._channel_tasks.pop(name, None)
        try:
            await channel.stop()
            logger.info("Stopped {} channel", name)
        except asyncio.CancelledError:
            if asyncio.current_task() and asyncio.current_task().cancelling():
                raise
            logger.debug("Channel {} stop task was already cancelled", name)
        except Exception:
            logger.exception("Error stopping {}", name)

        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return True

    def _is_known_channel_name(self, name: str) -> bool:
        from nanobot.channels.registry import discover_channel_names, discover_plugins

        return name in set(discover_channel_names()) or name in discover_plugins()

    def _load_channel_class(self, name: str) -> type[BaseChannel] | None:
        from nanobot.channels.registry import discover_channel_names, discover_enabled

        names = discover_channel_names()
        return discover_enabled({name}, _names=names, warn_import_errors=True).get(name)

    async def apply_channel_feature_action(
        self,
        action: str,
        name: str,
        instance_id: str = "",
    ) -> dict[str, Any]:
        """Apply a WebUI channel enable/disable action without restarting the gateway.

        Returns a small transport-neutral result. ``handled=False`` means the
        optional feature is not a channel and should keep the default feature
        response semantics.
        """
        name = name.strip()
        instance_id = instance_id.strip()
        if not name or not self._is_known_channel_name(name):
            return {"handled": False}
        if name == "websocket":
            return {
                "handled": True,
                "ok": False,
                "requires_restart": True,
                "message": "WebSocket hosts the WebUI and is applied on restart.",
            }

        from nanobot.config.loader import load_config

        self.config = load_config()
        section = self._channel_section(name)
        cls = self._load_channel_class(name)
        if cls is None:
            return {
                "handled": True,
                "ok": False,
                "requires_restart": True,
                "message": f"{name} channel could not be loaded.",
            }

        if action == "disable":
            if instance_id:
                runtime_name = channel_runtime_name(cls, instance_id)
                runtime_names = (
                    [runtime_name]
                    if self._channel_owners.get(runtime_name) == name
                    else []
                )
            else:
                runtime_names = [
                    runtime_name
                    for runtime_name, owner in self._channel_owners.items()
                    if owner == name
                ]
            stopped = False
            for runtime_name in runtime_names:
                stopped = await self._stop_channel(runtime_name) or stopped
                self.channels.pop(runtime_name, None)
                self._channel_owners.pop(runtime_name, None)
            return {
                "handled": True,
                "ok": True,
                "requires_restart": False,
                "message": f"{name} channel stopped." if stopped else f"{name} channel disabled.",
            }

        if action != "enable":
            return {"handled": True, "ok": False, "requires_restart": True}

        specs = channel_instance_specs(cls, section) if section is not None else []
        if instance_id:
            specs = [spec for spec in specs if spec.instance_id == instance_id]
        if not specs:
            return {
                "handled": True,
                "ok": False,
                "requires_restart": True,
                "message": f"{name} channel config was not enabled.",
            }

        runtime_specs = [
            (channel_runtime_name(cls, spec.instance_id), spec)
            for spec in specs
        ]
        collisions = [
            runtime_name
            for runtime_name, _spec in runtime_specs
            if (
                runtime_name in self.channels
                and self._channel_owners.get(runtime_name) != name
            )
        ]
        if collisions:
            return {
                "handled": True,
                "ok": False,
                "requires_restart": True,
                "message": (
                    "Channel runtime name(s) already owned by another channel: "
                    + ", ".join(sorted(collisions))
                ),
            }

        try:
            built = [
                (
                    runtime_name,
                    self._build_channel(
                        name,
                        cls,
                        spec.config,
                        runtime_name=runtime_name,
                    ),
                )
                for runtime_name, spec in runtime_specs
            ]
        except Exception as exc:
            logger.exception("Failed to build {} channel after settings change", name)
            return {
                "handled": True,
                "ok": False,
                "requires_restart": True,
                "message": f"{name} channel could not be started: {exc}",
            }

        for runtime_name, _channel in built:
            if runtime_name in self.channels:
                await self._stop_channel(runtime_name)

        for runtime_name, channel in built:
            self.channels[runtime_name] = channel
            self._channel_owners[runtime_name] = name
            if self._started:
                self._start_channel_task(runtime_name, channel)
            logger.info("{} channel applied without restart", runtime_name)
        return {
            "handled": True,
            "ok": True,
            "requires_restart": False,
            "message": f"{cls.display_name} channel applied without restart.",
        }

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        self._started = True
        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            tasks.append(self._start_channel_task(name, channel))

        self._notify_restart_done_if_needed()

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)

    def _notify_restart_done_if_needed(self) -> asyncio.Task[None] | None:
        """Schedule restart completion after the target channel starts."""
        notice = consume_restart_notice_from_env()
        if not notice:
            return None
        return asyncio.create_task(self._send_restart_notice_when_started(notice))

    async def _send_restart_notice_when_started(
        self,
        notice: RestartNotice,
        *,
        timeout_s: float = _RESTART_NOTICE_START_TIMEOUT_S,
        poll_s: float = _RESTART_NOTICE_START_POLL_S,
    ) -> None:
        """Deliver a restart notice after the target channel starts."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        target = self.channels.get(notice.channel)
        if target is None:
            logger.warning("Restart notice target channel is not enabled: {}", notice.channel)
            return

        while not target.is_running:
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning(
                    "Restart notice target did not start: {}:{}",
                    notice.channel,
                    notice.chat_id,
                )
                return
            await asyncio.sleep(min(poll_s, remaining))

        await self._send_with_retry(
            target,
            OutboundMessage(
                channel=notice.channel,
                chat_id=notice.chat_id,
                content=format_restart_completed_message(notice.started_at_raw),
                metadata=dict(notice.metadata or {}),
            ),
            deadline=deadline,
        )

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")
        self._started = False

        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._dispatch_task

        # Stop all channels
        for name in list(self.channels):
            await self._stop_channel(name)

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

    async def _send_with_retry(
        self,
        channel: BaseChannel,
        msg: OutboundMessage,
        *,
        deadline: float | None = None,
    ) -> None:
        """Send a message with retry on failure using exponential backoff.

        When deadline is provided, retry until that monotonic time instead of
        stopping at the configured attempt limit.

        Note: CancelledError is re-raised to allow graceful shutdown.
        """
        max_attempts = max(self.config.channels.send_max_retries, 1)
        attempt = 0

        while True:
            attempt += 1
            try:
                await self._send_once(channel, msg)
                return  # Send succeeded
            except asyncio.CancelledError:
                raise  # Propagate cancellation for graceful shutdown
            except Exception as e:
                loop = asyncio.get_running_loop()
                exhausted = (
                    attempt >= max_attempts
                    if deadline is None
                    else loop.time() >= deadline
                )
                if exhausted:
                    logger.exception(
                        "Failed to send to {} after {} attempts",
                        msg.channel, attempt,
                    )
                    return
                delay = _SEND_RETRY_DELAYS[min(attempt - 1, len(_SEND_RETRY_DELAYS) - 1)]
                if deadline is not None:
                    delay = min(delay, max(0.0, deadline - loop.time()))
                attempt_label = str(attempt)
                if deadline is None:
                    attempt_label = f"{attempt}/{max_attempts}"
                logger.warning(
                    "Send to {} failed (attempt {}): {}, retrying in {}s",
                    msg.channel, attempt_label, type(e).__name__, delay,
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
