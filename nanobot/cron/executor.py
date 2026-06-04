"""Cron job execution for the gateway runtime."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

import nanobot.utils.evaluator as evaluator
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cron.types import CronJob


class DeliverToChannel(Protocol):
    def __call__(
        self,
        msg: OutboundMessage,
        *,
        record: bool = False,
        session_key: str | None = None,
    ) -> Awaitable[None]: ...


ChannelLookup = Callable[[str], Any | None]
EvaluateResponse = Callable[..., Awaitable[bool]]
HeartbeatTaskDetector = Callable[[str], bool]
HeartbeatTargetPicker = Callable[[], tuple[str, str]]


class _CronStreamBuffer:
    def __init__(
        self,
        *,
        channel: str,
        chat_id: str,
        channel_meta: dict[str, Any],
        base_id: str,
    ) -> None:
        self.channel = channel
        self.chat_id = chat_id
        self.channel_meta = channel_meta
        self.base_id = base_id
        self.segment = 0
        self.events: list[OutboundMessage] = []
        self.has_delta = False

    def _stream_id(self) -> str:
        return f"{self.base_id}:{self.segment}"

    async def on_stream(self, delta: str) -> None:
        meta = dict(self.channel_meta)
        meta["_stream_delta"] = True
        meta["_stream_id"] = self._stream_id()
        self.events.append(OutboundMessage(
            channel=self.channel,
            chat_id=self.chat_id,
            content=delta,
            metadata=meta,
        ))
        if delta:
            self.has_delta = True

    async def on_stream_end(self, *, resuming: bool = False) -> None:
        meta = dict(self.channel_meta)
        meta["_stream_end"] = True
        meta["_resuming"] = resuming
        meta["_stream_id"] = self._stream_id()
        self.events.append(OutboundMessage(
            channel=self.channel,
            chat_id=self.chat_id,
            content="",
            metadata=meta,
        ))
        self.segment += 1

    async def publish(self, bus: MessageBus) -> None:
        for event in self.events:
            await bus.publish_outbound(event)


class CronJobExecutor:
    """Runs scheduled cron jobs through the agent and optional channel delivery."""

    def __init__(
        self,
        *,
        agent: Any,
        bus: MessageBus,
        deliver_to_channel: DeliverToChannel,
        get_channel: ChannelLookup | None = None,
        evaluate_response: EvaluateResponse | None = None,
        heartbeat_workspace: Path | None = None,
        heartbeat_preamble: str = "",
        heartbeat_has_active_tasks: HeartbeatTaskDetector | None = None,
        pick_heartbeat_target: HeartbeatTargetPicker | None = None,
        heartbeat_keep_recent_messages: int = 8,
    ) -> None:
        self.agent = agent
        self.bus = bus
        self.deliver_to_channel = deliver_to_channel
        self.get_channel = get_channel or (lambda _channel: None)
        self.evaluate_response = evaluate_response or evaluator.evaluate_response
        self.heartbeat_workspace = heartbeat_workspace
        self.heartbeat_preamble = heartbeat_preamble
        self.heartbeat_has_active_tasks = heartbeat_has_active_tasks
        self.pick_heartbeat_target = pick_heartbeat_target
        self.heartbeat_keep_recent_messages = heartbeat_keep_recent_messages

    async def run(self, job: CronJob) -> str | None:
        if job.name == "dream":
            return await self._run_dream()
        if job.name == "heartbeat":
            return await self._run_heartbeat()

        return await self._run_agent_turn(job)

    async def _run_dream(self) -> None:
        from nanobot.agent.memory import MemoryStore

        dream_session_key = MemoryStore.dream_session_key
        build_dream_commit_message = MemoryStore.build_dream_commit_message
        prune_dream_sessions = MemoryStore.prune_dream_sessions

        store = self.agent.context.memory
        resp = None
        try:
            result = store.build_dream_prompt()
            if result is None:
                logger.info("Dream: nothing to process")
                return None
            prompt, last_cursor = result
            resp = await self.agent.process_direct(
                prompt,
                session_key=dream_session_key(),
                ephemeral=True,
                tools=store.build_dream_tools(),
                on_progress=self._silent,
            )
            if MemoryStore.dream_run_completed(resp):
                store.set_last_dream_cursor(last_cursor)
                logger.info("Dream cron job completed, cursor advanced to {}", last_cursor)
            else:
                logger.warning(
                    "Dream cron job did not complete; cursor remains at {}",
                    store.get_last_dream_cursor(),
                )
        except Exception:
            logger.exception("Dream cron job failed")
        finally:
            if store.git.is_initialized():
                msg = build_dream_commit_message(
                    "dream: periodic memory consolidation", resp,
                )
                sha = store.git.auto_commit(msg)
                if sha:
                    logger.info("Dream commit: {}", sha)
            store.compact_history()
            prune_dream_sessions(self.agent.sessions.sessions_dir)
        return None

    async def _run_heartbeat(self) -> str | None:
        if (
            self.heartbeat_workspace is None
            or self.heartbeat_has_active_tasks is None
            or self.pick_heartbeat_target is None
        ):
            logger.warning("Heartbeat cron job skipped: executor is not configured for heartbeat")
            return None

        heartbeat_file = self.heartbeat_workspace / "HEARTBEAT.md"
        try:
            content = heartbeat_file.read_text(encoding="utf-8")
        except OSError:
            logger.debug("Heartbeat: HEARTBEAT.md missing")
            return None
        if not self.heartbeat_has_active_tasks(content):
            logger.debug("Heartbeat: HEARTBEAT.md has no active tasks")
            return None

        channel, chat_id = self.pick_heartbeat_target()
        if channel == "cli":
            return None

        prompt = (
            self.heartbeat_preamble
            + f"Review the following HEARTBEAT.md and report any active tasks:\n\n{content}"
        )

        message_tool = self._tool("message")
        suppress_token = None
        if isinstance(message_tool, MessageTool):
            suppress_token = message_tool.set_suppress_delivery(True)
        try:
            resp = await self.agent.process_direct(
                prompt,
                session_key="heartbeat",
                channel=channel,
                chat_id=chat_id,
                on_progress=self._silent,
            )
        finally:
            if isinstance(message_tool, MessageTool) and suppress_token is not None:
                message_tool.reset_suppress_delivery(suppress_token)
        response = resp.content if resp else ""

        session = self.agent.sessions.get_or_create("heartbeat")
        session.retain_recent_legal_suffix(self.heartbeat_keep_recent_messages)
        self.agent.sessions.save(session)

        if not response:
            return None

        should_notify = await self.evaluate_response(
            response, prompt, self.agent.provider, self.agent.model,
            default_notify=False,
        )
        if should_notify:
            logger.info("Heartbeat: completed, delivering response")
            await self.deliver_to_channel(
                OutboundMessage(channel=channel, chat_id=chat_id, content=response),
                record=True,
            )
        else:
            logger.info("Heartbeat: silenced by post-run evaluation")
        return response

    async def _run_agent_turn(self, job: CronJob) -> str | None:
        reminder_note = self._reminder_note(job)
        cron_tool = self._tool("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)

        message_tool = self._tool("message")
        message_record_token = None
        if isinstance(message_tool, MessageTool):
            message_record_token = message_tool.set_record_channel_delivery(True)

        channel_name = job.payload.channel or "cli"
        chat_id = job.payload.to or "direct"
        stream = self._stream_buffer(job, channel_name=channel_name, chat_id=chat_id)

        try:
            resp = await self.agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=channel_name,
                chat_id=chat_id,
                on_progress=self._silent,
                on_stream=stream.on_stream if stream else None,
                on_stream_end=stream.on_stream_end if stream else None,
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)
            if isinstance(message_tool, MessageTool) and message_record_token is not None:
                message_tool.reset_record_channel_delivery(message_record_token)

        response = resp.content if resp else ""

        if job.payload.deliver and isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            await self._publish_turn_end_if_needed(job, channel_name=channel_name, chat_id=chat_id)
            return response

        delivered = False
        if job.payload.deliver and job.payload.to and response:
            should_notify = await self.evaluate_response(
                response, reminder_note, self.agent.provider, self.agent.model,
            )
            if should_notify:
                meta = dict(job.payload.channel_meta)
                if stream and stream.has_delta:
                    await stream.publish(self.bus)
                    meta["_streamed"] = True
                await self.deliver_to_channel(
                    OutboundMessage(
                        channel=channel_name,
                        chat_id=chat_id,
                        content=response,
                        metadata=meta,
                    ),
                    record=True,
                    session_key=job.payload.session_key,
                )
                delivered = True

        if delivered:
            await self._publish_turn_end_if_needed(job, channel_name=channel_name, chat_id=chat_id)
        return response

    def _tool(self, name: str) -> Any | None:
        tools = getattr(self.agent, "tools", {})
        if hasattr(tools, "get"):
            return tools.get(name)
        return None

    def _stream_buffer(
        self,
        job: CronJob,
        *,
        channel_name: str,
        chat_id: str,
    ) -> _CronStreamBuffer | None:
        target_channel = self.get_channel(channel_name)
        wants_stream = bool(
            job.payload.deliver
            and job.payload.to
            and target_channel is not None
            and target_channel.supports_streaming
        )
        if not wants_stream:
            return None
        return _CronStreamBuffer(
            channel=channel_name,
            chat_id=chat_id,
            channel_meta=job.payload.channel_meta,
            base_id=f"cron:{job.id}:{time.time_ns()}",
        )

    async def _publish_turn_end_if_needed(
        self,
        job: CronJob,
        *,
        channel_name: str,
        chat_id: str,
    ) -> None:
        if channel_name != "websocket" or not job.payload.to:
            return
        await self.bus.publish_outbound(OutboundMessage(
            channel=channel_name,
            chat_id=chat_id,
            content="",
            metadata={**job.payload.channel_meta, "_turn_end": True},
        ))

    @staticmethod
    async def _silent(*_args: Any, **_kwargs: Any) -> None:
        pass

    @staticmethod
    def _reminder_note(job: CronJob) -> str:
        return (
            "The scheduled time has arrived. Deliver this reminder to the user now, "
            "as a brief and natural message in their language. Speak directly to them — "
            "do not narrate progress, summarize, include user IDs, or add status reports "
            "like 'Done' or 'Reminded'.\n\n"
            f"Reminder: {job.payload.message}"
        )
