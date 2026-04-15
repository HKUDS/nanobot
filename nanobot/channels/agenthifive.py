"""AgentHiFive vault-managed channel integration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from agenthifive_nanobot.auth import build_runtime_config_from_mcp_server
from agenthifive_nanobot.vault_client import VaultClient
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_runtime_subdir
from nanobot.config.schema import Base


class AgentHiFiveTelegramConfig(Base):
    """Vault-managed Telegram channel settings."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    reply_to_message: bool = True


class AgentHiFiveSlackConfig(Base):
    """Vault-managed Slack channel settings."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    reply_in_thread: bool = True
    channel_types: list[str] = Field(
        default_factory=lambda: ["im", "public_channel", "private_channel", "mpim"]
    )


class AgentHiFiveProvidersConfig(Base):
    """Provider-specific channel settings."""

    telegram: AgentHiFiveTelegramConfig = Field(default_factory=AgentHiFiveTelegramConfig)
    slack: AgentHiFiveSlackConfig = Field(default_factory=AgentHiFiveSlackConfig)


class AgentHiFiveConfig(Base):
    """AgentHiFive channel configuration."""

    enabled: bool = False
    providers: AgentHiFiveProvidersConfig = Field(default_factory=AgentHiFiveProvidersConfig)
    poll_timeout_s: int = 30
    backoff_initial_ms: int = 2_000
    backoff_max_ms: int = 30_000
    state_dir: str | None = None


def _build_agenthifive_vault_client() -> VaultClient:
    """Create a VaultClient from the active NanoBot config."""
    from nanobot.config.loader import get_config_path, load_config, resolve_config_env_vars

    config = resolve_config_env_vars(load_config(get_config_path()))
    server = config.tools.mcp_servers.get("agenthifive")
    if server is None:
        raise RuntimeError(
            "AgentHiFive MCP server is not configured in tools.mcp_servers.agenthifive"
        )

    runtime = build_runtime_config_from_mcp_server(server)
    return VaultClient(base_url=runtime.base_url, auth=runtime.auth, timeout=runtime.timeout)


class AgentHiFiveChannel(BaseChannel):
    """Vault-managed inbound/outbound channels backed by AgentHiFive."""

    name = "agenthifive"
    display_name = "AgentHiFive"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return AgentHiFiveConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = AgentHiFiveConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: AgentHiFiveConfig = config
        self._vault: VaultClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()
        self._slack_channel_types_override: list[str] | None = None

    async def start(self) -> None:
        """Start enabled AgentHiFive channel pollers."""
        self._running = True
        self._stop_event = asyncio.Event()
        self._vault = _build_agenthifive_vault_client()
        # Telegram long-poll requests must outlive the provider-side poll timeout,
        # otherwise the local HTTP client raises ReadTimeout before Telegram responds.
        min_timeout = max(float(self.config.poll_timeout_s) + 10.0, 10.0)
        current_timeout = float(getattr(self._vault, "timeout", 0.0) or 0.0)
        if current_timeout < min_timeout:
            self._vault.timeout = min_timeout
        await self._vault.start()

        if self.config.providers.telegram.enabled:
            self._tasks.append(asyncio.create_task(self._poll_telegram()))
            logger.info("AgentHiFive Telegram channel enabled")
        if self.config.providers.slack.enabled:
            self._tasks.append(asyncio.create_task(self._poll_slack()))
            logger.info("AgentHiFive Slack channel enabled")

        if not self._tasks:
            logger.warning("AgentHiFive channel is enabled but no providers are turned on")

        try:
            await self._stop_event.wait()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop all background pollers."""
        self._running = False
        self._stop_event.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("AgentHiFive channel task failed during shutdown: {}", exc)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message back through the vault-managed provider."""
        if not self._vault:
            raise RuntimeError("AgentHiFive channel is not running")
        if msg.media:
            raise RuntimeError(
                "AgentHiFive channel does not yet support sending local file attachments"
            )

        provider, target = self._parse_target(msg.chat_id)
        if provider == "telegram":
            await self._send_telegram(msg, target)
            return
        if provider == "slack":
            await self._send_slack(msg, target)
            return
        raise RuntimeError(f"Unsupported AgentHiFive provider target: {provider}")

    async def _send_telegram(self, msg: OutboundMessage, target: str) -> None:
        """Send a vault-managed Telegram reply."""
        assert self._vault is not None

        chat_id, thread_id = self._parse_telegram_target(target)
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": msg.content or " ",
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        if self.config.providers.telegram.reply_to_message and msg.metadata.get("message_id"):
            body["reply_to_message_id"] = msg.metadata["message_id"]

        result = await self._vault.execute(
            {
                "model": "B",
                "service": "telegram",
                "method": "POST",
                "url": "https://api.telegram.org/bot/sendMessage",
                "body": body,
                "context": {
                    "tool": "channel_plugin",
                    "action": "send_message",
                    "channel": "telegram",
                },
            }
        )
        if result.blocked:
            reason = result.blocked.reason
            if result.blocked.approval_request_id:
                reason += f" (approvalRequestId: {result.blocked.approval_request_id})"
            raise RuntimeError(reason)
        if result.status_code < 200 or result.status_code >= 300:
            raise RuntimeError(f"Telegram send failed with HTTP {result.status_code}")

    async def _send_slack(self, msg: OutboundMessage, target: str) -> None:
        """Send a vault-managed Slack reply."""
        assert self._vault is not None

        channel_id, thread_ts = self._parse_slack_target(target)
        body: dict[str, Any] = {
            "channel": channel_id,
            "text": msg.content or " ",
        }
        if self.config.providers.slack.reply_in_thread:
            reply_thread = thread_ts or msg.metadata.get("thread_ts")
            if reply_thread:
                body["thread_ts"] = reply_thread

        result = await self._vault.execute(
            {
                "model": "B",
                "service": "slack",
                "method": "POST",
                "url": "https://slack.com/api/chat.postMessage",
                "body": body,
                "context": {
                    "tool": "channel_plugin",
                    "action": "send_message",
                    "channel": "slack",
                },
            }
        )
        if result.blocked:
            reason = result.blocked.reason
            if result.blocked.approval_request_id:
                reason += f" (approvalRequestId: {result.blocked.approval_request_id})"
            raise RuntimeError(reason)
        if result.status_code < 200 or result.status_code >= 300:
            raise RuntimeError(f"Slack send failed with HTTP {result.status_code}")

    def is_allowed(self, sender_id: str) -> bool:
        """Use per-provider allowlists; empty allowlist falls back to the vault policy."""
        if sender_id.startswith("telegram:"):
            allow_list = self.config.providers.telegram.allow_from
            if not allow_list:
                return True

            raw = sender_id.removeprefix("telegram:")
            if "|" not in raw:
                return raw in allow_list
            user_id, username = raw.split("|", 1)
            return user_id in allow_list or username in allow_list
        if sender_id.startswith("slack:"):
            allow_list = self.config.providers.slack.allow_from
            if not allow_list:
                return True
            raw = sender_id.removeprefix("slack:")
            return raw in allow_list

        return False

    async def _poll_telegram(self) -> None:
        """Long-poll Telegram updates through the vault."""
        assert self._vault is not None

        offset = self._load_offset("telegram")
        backoff_ms = self.config.backoff_initial_ms

        while self._running:
            try:
                result = await self._vault.execute(
                    {
                        "model": "B",
                        "service": "telegram",
                        "method": "POST",
                        "url": "https://api.telegram.org/bot/getUpdates",
                        "body": {
                            "offset": offset,
                            "timeout": self.config.poll_timeout_s,
                            "allowed_updates": ["message"],
                        },
                        "context": {
                            "tool": "channel_plugin",
                            "action": "receive_message",
                            "channel": "telegram",
                        },
                    }
                )

                if result.blocked:
                    logger.warning("AgentHiFive Telegram poll blocked: {}", result.blocked.reason)
                    await asyncio.sleep(backoff_ms / 1000.0)
                    backoff_ms = min(backoff_ms * 2, self.config.backoff_max_ms)
                    continue

                body = result.body if isinstance(result.body, dict) else {}
                if body.get("error_code") == 409 or result.status_code == 409:
                    logger.warning("AgentHiFive Telegram poller hit 409 conflict; backing off")
                    await asyncio.sleep(backoff_ms / 1000.0)
                    backoff_ms = min(backoff_ms * 2, self.config.backoff_max_ms)
                    continue

                updates = body.get("result")
                if not body.get("ok") or not isinstance(updates, list):
                    logger.warning(
                        "AgentHiFive Telegram poll unexpected response (status={}): {}",
                        result.status_code,
                        str(body)[:200],
                    )
                    await asyncio.sleep(backoff_ms / 1000.0)
                    backoff_ms = min(backoff_ms * 2, self.config.backoff_max_ms)
                    continue

                backoff_ms = self.config.backoff_initial_ms

                for update in updates:
                    if not isinstance(update, dict):
                        continue
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    message = update.get("message")
                    if isinstance(message, dict):
                        await self._handle_telegram_message(message)

                if updates:
                    self._save_offset("telegram", offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                logger.warning(
                    "AgentHiFive Telegram poll failed: {}: {}",
                    type(exc).__name__,
                    exc,
                )
                await asyncio.sleep(backoff_ms / 1000.0)
                backoff_ms = min(backoff_ms * 2, self.config.backoff_max_ms)

    async def _poll_slack(self) -> None:
        """Poll Slack conversations through the vault."""
        assert self._vault is not None

        state = self._load_json_state("slack-watermarks", {"channels": {}})
        backoff_ms = self.config.backoff_initial_ms

        while self._running:
            try:
                channels = await self._slack_discover_channels()
                if channels is None:
                    await asyncio.sleep(backoff_ms / 1000.0)
                    backoff_ms = min(backoff_ms * 2, self.config.backoff_max_ms)
                    continue

                for channel in channels:
                    channel_id = channel.get("id")
                    if not isinstance(channel_id, str):
                        continue
                    oldest = state.get("channels", {}).get(channel_id, {}).get("oldest")
                    messages = await self._slack_poll_channel(
                        channel_id, str(oldest) if oldest else None
                    )
                    if messages is None:
                        continue
                    for message in reversed(messages):
                        if not isinstance(message, dict):
                            continue
                        if self._slack_should_skip_message(message):
                            continue
                        await self._handle_slack_message(message, channel)
                    if messages:
                        latest_ts = self._slack_latest_ts(messages)
                        if latest_ts:
                            state.setdefault("channels", {})[channel_id] = {"oldest": latest_ts}
                self._save_json_state("slack-watermarks", state)
                backoff_ms = self.config.backoff_initial_ms
                await asyncio.sleep(15.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("AgentHiFive Slack poll failed: {}", exc)
                await asyncio.sleep(backoff_ms / 1000.0)
                backoff_ms = min(backoff_ms * 2, self.config.backoff_max_ms)

    async def _slack_discover_channels(self) -> list[dict[str, Any]] | None:
        """List Slack conversations the vault-managed bot can access."""
        assert self._vault is not None

        channel_types = list(
            self._slack_channel_types_override or self.config.providers.slack.channel_types
        )
        if not channel_types:
            return []

        params = {
            "types": ",".join(channel_types),
            "exclude_archived": "true",
            "limit": "200",
        }
        query = "&".join(f"{key}={value}" for key, value in params.items())
        result = await self._vault.execute(
            {
                "model": "B",
                "service": "slack",
                "method": "POST",
                "url": f"https://slack.com/api/conversations.list?{query}",
                "context": {
                    "tool": "channel_plugin",
                    "action": "receive_message",
                    "channel": "slack",
                },
            }
        )
        if result.blocked:
            logger.warning("AgentHiFive Slack discovery blocked: {}", result.blocked.reason)
            return None

        body = result.body if isinstance(result.body, dict) else {}
        channels = body.get("channels")
        fallback_types = self._slack_fallback_channel_types(body, channel_types)
        if fallback_types is not None:
            self._slack_channel_types_override = fallback_types
            return await self._slack_discover_channels()
        if not body.get("ok") or not isinstance(channels, list):
            logger.warning(
                "AgentHiFive Slack discovery returned unexpected body: {}", str(body)[:200]
            )
            return None

        visible = []
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            if channel.get("is_im") or channel.get("is_member", False):
                visible.append(channel)
        return visible

    def _slack_fallback_channel_types(
        self,
        body: dict[str, Any],
        requested_types: list[str],
    ) -> list[str] | None:
        """Drop Slack conversation types that require scopes missing from the current connection."""
        if body.get("error") != "missing_scope":
            return None

        scope_map = {
            "channels:read": {"public_channel"},
            "groups:read": {"private_channel"},
            "im:read": {"im"},
            "mpim:read": {"mpim"},
        }
        needed_scopes = [
            scope.strip() for scope in str(body.get("needed", "")).split(",") if scope.strip()
        ]
        removed_types = {
            channel_type for scope in needed_scopes for channel_type in scope_map.get(scope, set())
        }
        fallback_types = [
            channel_type for channel_type in requested_types if channel_type not in removed_types
        ]
        if fallback_types == requested_types:
            return None

        if removed_types:
            logger.warning(
                "AgentHiFive Slack discovery is skipping channel types without granted scopes: {}",
                ", ".join(sorted(removed_types)),
            )
        else:
            logger.warning(
                "AgentHiFive Slack discovery is retrying without unsupported scopes: {}",
                ", ".join(needed_scopes) or "unknown",
            )
        return fallback_types

    async def _slack_poll_channel(
        self,
        channel_id: str,
        oldest: str | None,
    ) -> list[dict[str, Any]] | None:
        """Poll a single Slack conversation for new messages."""
        assert self._vault is not None

        query = [f"channel={channel_id}", "limit=20"]
        if oldest:
            query.extend([f"oldest={oldest}", "inclusive=false"])
        result = await self._vault.execute(
            {
                "model": "B",
                "service": "slack",
                "method": "POST",
                "url": f"https://slack.com/api/conversations.history?{'&'.join(query)}",
                "context": {
                    "tool": "channel_plugin",
                    "action": "receive_message",
                    "channel": "slack",
                },
            }
        )
        if result.blocked:
            logger.warning(
                "AgentHiFive Slack history blocked for {}: {}",
                channel_id,
                result.blocked.reason,
            )
            return None

        body = result.body if isinstance(result.body, dict) else {}
        messages = body.get("messages")
        if not body.get("ok") or not isinstance(messages, list):
            logger.warning(
                "AgentHiFive Slack history returned unexpected body for {}: {}",
                channel_id,
                str(body)[:200],
            )
            return None
        return messages

    async def _handle_slack_message(
        self,
        message: dict[str, Any],
        channel_info: dict[str, Any],
    ) -> None:
        """Convert a Slack message into a NanoBot inbound message."""
        channel_id = channel_info.get("id")
        sender_id = message.get("user")
        ts = message.get("ts")
        if (
            not isinstance(channel_id, str)
            or not isinstance(sender_id, str)
            or not isinstance(ts, str)
        ):
            return

        text = str(message.get("text") or "").strip() or "[unsupported message]"
        chat_id = self._build_slack_target(channel_id, message.get("thread_ts"))
        metadata = {
            "provider": "slack",
            "channel_id": channel_id,
            "message_id": ts,
            "thread_ts": message.get("thread_ts"),
            "channel_type": (
                "im"
                if channel_info.get("is_im")
                else "channel"
                if channel_info.get("is_channel")
                else "group"
            ),
        }

        await self._handle_message(
            sender_id=f"slack:{sender_id}",
            chat_id=chat_id,
            content=text,
            metadata=metadata,
        )

    async def _handle_telegram_message(self, message: dict[str, Any]) -> None:
        """Convert a Telegram update into a NanoBot inbound message."""
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        user = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat_id = chat.get("id")
        user_id = user.get("id")
        if chat_id is None or user_id is None:
            return

        content = str(message.get("text") or message.get("caption") or "").strip()
        if not content:
            content = "[unsupported message]"

        reply_to = (
            message.get("reply_to_message")
            if isinstance(message.get("reply_to_message"), dict)
            else None
        )
        if reply_to:
            reply_text = str(reply_to.get("text") or "").strip()
            if reply_text:
                content = f"[Reply to: {reply_text}]\n{content}"

        sender_id = self._build_telegram_sender_id(user)
        target = self._build_telegram_target(chat_id, message.get("message_thread_id"))
        metadata = {
            "provider": "telegram",
            "message_id": message.get("message_id"),
            "message_thread_id": message.get("message_thread_id"),
            "reply_to_message_id": reply_to.get("message_id") if reply_to else None,
            "user_id": user_id,
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "chat_type": chat.get("type"),
        }

        await self._handle_message(
            sender_id=sender_id,
            chat_id=target,
            content=content,
            metadata=metadata,
        )

    @staticmethod
    def _parse_target(chat_id: str) -> tuple[str, str]:
        if ":" not in chat_id:
            raise RuntimeError(f"Invalid AgentHiFive chat target: {chat_id}")
        provider, target = chat_id.split(":", 1)
        return provider, target

    @staticmethod
    def _parse_telegram_target(target: str) -> tuple[str, int | None]:
        if ":topic:" not in target:
            return target, None
        chat_id, thread = target.split(":topic:", 1)
        return chat_id, int(thread)

    @staticmethod
    def _build_telegram_target(chat_id: Any, thread_id: Any) -> str:
        base = f"telegram:{chat_id}"
        if thread_id is None:
            return base
        return f"{base}:topic:{thread_id}"

    @staticmethod
    def _parse_slack_target(target: str) -> tuple[str, str | None]:
        if ":thread:" not in target:
            return target, None
        channel_id, thread_ts = target.split(":thread:", 1)
        return channel_id, thread_ts

    @staticmethod
    def _build_slack_target(channel_id: Any, thread_ts: Any) -> str:
        base = f"slack:{channel_id}"
        if thread_ts is None:
            return base
        return f"{base}:thread:{thread_ts}"

    @staticmethod
    def _slack_should_skip_message(message: dict[str, Any]) -> bool:
        subtype = message.get("subtype")
        if message.get("bot_id"):
            return True
        if subtype in {
            "message_changed",
            "message_deleted",
            "message_replied",
            "channel_join",
            "channel_leave",
            "thread_broadcast",
        }:
            return True
        return bool(subtype and subtype not in {"file_share", "bot_message"})

    @staticmethod
    def _slack_latest_ts(messages: list[dict[str, Any]]) -> str | None:
        timestamps = [str(msg.get("ts")) for msg in messages if msg.get("ts") is not None]
        return max(timestamps, default=None)

    @staticmethod
    def _build_telegram_sender_id(user: dict[str, Any]) -> str:
        user_id = str(user.get("id", ""))
        username = str(user.get("username") or "").strip()
        return f"telegram:{user_id}|{username}" if username else f"telegram:{user_id}"

    def _state_dir(self) -> Path:
        if self.config.state_dir:
            return Path(self.config.state_dir).expanduser()
        return get_runtime_subdir("agenthifive")

    def _offset_path(self, provider: Literal["telegram"]) -> Path:
        return self._state_dir() / f"{provider}-offset.json"

    def _load_offset(self, provider: Literal["telegram"]) -> int:
        path = self._offset_path(provider)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            offset = data.get("offset")
            return int(offset) if offset is not None else 0
        except Exception:
            return 0

    def _save_offset(self, provider: Literal["telegram"], offset: int) -> None:
        path = self._offset_path(provider)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps({"offset": offset}, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to persist AgentHiFive {} offset: {}", provider, exc)

    def _state_path(self, name: str) -> Path:
        return self._state_dir() / f"{name}.json"

    def _load_json_state(self, name: str, default: dict[str, Any]) -> dict[str, Any]:
        path = self._state_path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else dict(default)
        except Exception:
            return dict(default)

    def _save_json_state(self, name: str, state: dict[str, Any]) -> None:
        path = self._state_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to persist AgentHiFive state {}: {}", name, exc)
