"""Async message queue for decoupled channel-agent communication."""

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(
        self,
        *,
        workspace: Path | None = None,
        inbound_outbound_log_enabled: bool | None = None,
    ):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

        # 当调用方未显式传参时，回退到全局配置，避免在多处构造 MessageBus 时重复透传。
        resolved_workspace = workspace
        resolved_enabled = inbound_outbound_log_enabled
        if resolved_enabled is None:
            try:
                from nanobot.config.loader import load_config

                cfg = load_config()
                resolved_enabled = cfg.dispatch.inbound_outbound_log_enabled
                if resolved_workspace is None:
                    resolved_workspace = cfg.workspace_path
            except Exception:
                resolved_enabled = False

        self._inbound_outbound_log_enabled = bool(resolved_enabled)
        self._inbound_outbound_log_path: Path | None = None
        self._inbound_outbound_log_file: TextIOWrapper | None = None
        if self._inbound_outbound_log_enabled:
            if resolved_workspace is None:
                logger.warning(
                    "Inbound/outbound mixed logging enabled but workspace is missing; skip file logging"
                )
                self._inbound_outbound_log_enabled = False
            else:
                # 每次启动创建独立日志文件，避免跨次启动混写同一个 jsonl。
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                self._inbound_outbound_log_path = (
                    resolved_workspace / ".nanobot-logs" / "Log" / f"inbound_outbound-{stamp}.jsonl"
                )
                self._inbound_outbound_log_path.parent.mkdir(parents=True, exist_ok=True)
                self._inbound_outbound_log_file = self._inbound_outbound_log_path.open(
                    "a", encoding="utf-8"
                )

    def _jsonify(self, value: Any) -> Any:
        """Convert values to JSON-serializable structures for jsonl persistence."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if is_dataclass(value) and not isinstance(value, type):
            return self._jsonify(asdict(value))
        if isinstance(value, dict):
            return {str(k): self._jsonify(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._jsonify(v) for v in value]
        if isinstance(value, tuple):
            return [self._jsonify(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _append_io_record(self, direction: str, msg: InboundMessage | OutboundMessage) -> None:
        """Append one mixed inbound/outbound record into jsonl log file."""
        if not self._inbound_outbound_log_enabled or self._inbound_outbound_log_file is None:
            return

        record = {
            "recordedAt": datetime.now().isoformat(),
            "direction": direction,
            # 统一保存原始消息结构，方便后续离线还原与分析
            "message": self._jsonify(msg),
        }
        try:
            self._inbound_outbound_log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._inbound_outbound_log_file.flush()
        except Exception as exc:
            logger.warning("Failed to append inbound/outbound jsonl record: {}", exc)

    def close(self) -> None:
        """Close mixed inbound/outbound log file for current runtime."""
        if self._inbound_outbound_log_file is None:
            return
        try:
            self._inbound_outbound_log_file.close()
        finally:
            self._inbound_outbound_log_file = None

    @staticmethod
    def _preview_text(text: str, *, limit: int = 120) -> str:
        normalized = (text or "").replace("\r", " ").replace("\n", "\\n")
        if len(normalized) > limit:
            return f"{normalized[:limit]}..."
        return normalized

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        self._append_io_record("inbound", msg)
        await self.inbound.put(msg)
        logger.debug(
            "Bus inbound enqueue channel={} chat={} session_key={} queue_size={}",
            msg.channel,
            msg.chat_id,
            msg.session_key,
            self.inbound.qsize(),
        )

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        msg = await self.inbound.get()
        logger.debug(
            "Bus inbound dequeue channel={} chat={} session_key={} queue_size={}",
            msg.channel,
            msg.chat_id,
            msg.session_key,
            self.inbound.qsize(),
        )
        return msg

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        self._append_io_record("outbound", msg)
        await self.outbound.put(msg)
        logger.debug(
            "[OB-BUS] stage=enqueue channel={} chat={} kind={} chars={} q={} preview='{}'",
            msg.channel,
            msg.chat_id,
            "tool_hint"
            if bool((msg.metadata or {}).get("_tool_hint"))
            else "progress"
            if bool((msg.metadata or {}).get("_progress"))
            else "final",
            len(msg.content or ""),
            self.outbound.qsize(),
            self._preview_text(msg.content or ""),
        )

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        msg = await self.outbound.get()
        logger.debug(
            "[OB-BUS] stage=dequeue channel={} chat={} kind={} chars={} q={} preview='{}'",
            msg.channel,
            msg.chat_id,
            "tool_hint"
            if bool((msg.metadata or {}).get("_tool_hint"))
            else "progress"
            if bool((msg.metadata or {}).get("_progress"))
            else "final",
            len(msg.content or ""),
            self.outbound.qsize(),
            self._preview_text(msg.content or ""),
        )
        return msg

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
