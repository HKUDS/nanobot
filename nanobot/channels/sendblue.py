"""Sendblue iMessage channel with per-sender profile isolation."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from loguru import logger
from pydantic import Field

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_runtime_subdir
from nanobot.config.schema import Base, Config, MCPServerConfig
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload
from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import split_message, sync_workspace_templates

SENDBLUE_MAX_MESSAGE_LEN = 18_500  # Sendblue limit is 18,996; keep headroom.
_DEDUP_MAX = 5000
_READ_TIMEOUT_SECONDS = 5


class SendblueProfileConfig(Base):
    """One trusted Sendblue user profile."""

    phone: str = ""
    workspace: str = ""
    composio_user_id: str = ""


class SendblueConfig(Base):
    """Sendblue channel configuration."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 18791
    webhook_path: str = "/sendblue/webhook"
    webhook_secret: str = ""
    api_base: str = "https://api.sendblue.co"
    api_key_id: str = ""
    api_secret_key: str = ""
    from_number: str = ""
    status_callback: str = ""
    typing_indicators: bool = True
    typing_interval_seconds: float = Field(default=4.0, ge=1.0)
    typing_max_seconds: float = Field(default=120.0, ge=1.0)
    allow_from: list[str] = Field(default_factory=list)
    profiles: dict[str, SendblueProfileConfig] = Field(default_factory=dict)
    deny_message: str = ""
    process_outbound_webhooks: bool = False


def _normalize_phone(value: str | None) -> str:
    normalized = (value or "").strip()
    for char in (" ", "-", "(", ")"):
        normalized = normalized.replace(char, "")
    return normalized


def _profile_workspace(profile_id: str, profile: SendblueProfileConfig) -> Path:
    if profile.workspace:
        return Path(profile.workspace).expanduser()
    return Path.home() / ".nanobot" / "profiles" / profile_id


def _dedupe_path() -> Path:
    return get_runtime_subdir("sendblue") / "dedupe.json"


def _load_dedupe() -> OrderedDict[str, None]:
    path = _dedupe_path()
    if not path.exists():
        return OrderedDict()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Sendblue: failed to read dedupe store, starting fresh")
        return OrderedDict()
    items = raw if isinstance(raw, list) else []
    return OrderedDict((str(item), None) for item in items[-_DEDUP_MAX:])


def _save_dedupe(items: OrderedDict[str, None]) -> None:
    path = _dedupe_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(items.keys())[-_DEDUP_MAX:]), encoding="utf-8")


class _ProfileRuntime:
    """Owns one isolated AgentLoop/workspace for a Sendblue user."""

    def __init__(
        self,
        *,
        profile_id: str,
        profile: SendblueProfileConfig,
        root_config: Config,
        channel_config: SendblueConfig,
        channel: "SendblueChannel",
    ) -> None:
        self.profile_id = profile_id
        self.profile = profile
        self.root_config = root_config
        self.channel_config = channel_config
        self.channel = channel
        self.bus = MessageBus()
        self.workspace = _profile_workspace(profile_id, profile)
        self.sessions = SessionManager(self.workspace)
        self.cron = CronService(self.workspace / "cron" / "jobs.json")
        self.provider = self._make_provider()
        self.agent = self._make_agent()
        self._tasks: list[asyncio.Task] = []
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def _profile_config(self) -> Config:
        cfg = self.root_config.model_copy(deep=True)
        cfg.agents.defaults.workspace = str(self.workspace)
        composio = cfg.tools.composio
        if composio.enabled and composio.api_key and composio.mcp_server_id:
            user_id = self.profile.composio_user_id or self.profile_id
            base = composio.base_url.rstrip("/")
            server_id = composio.mcp_server_id.strip("/")
            cfg.tools.mcp_servers = dict(cfg.tools.mcp_servers)
            cfg.tools.mcp_servers["composio"] = MCPServerConfig(
                type="streamableHttp",
                url=f"{base}/{server_id}?user_id={user_id}",
                headers={"x-api-key": composio.api_key},
            )
        return cfg

    def _make_provider(self):
        from nanobot.nanobot import _make_provider

        return _make_provider(self._profile_config())

    def _make_agent(self) -> AgentLoop:
        cfg = self._profile_config()
        defaults = cfg.agents.defaults
        return AgentLoop(
            bus=self.bus,
            provider=self.provider,
            workspace=self.workspace,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=defaults.context_window_tokens,
            context_block_limit=defaults.context_block_limit,
            max_tool_result_chars=defaults.max_tool_result_chars,
            provider_retry_mode=defaults.provider_retry_mode,
            web_config=cfg.tools.web,
            exec_config=cfg.tools.exec,
            cron_service=self.cron,
            restrict_to_workspace=cfg.tools.restrict_to_workspace,
            session_manager=self.sessions,
            mcp_servers=cfg.tools.mcp_servers,
            channels_config=cfg.channels,
            timezone=defaults.timezone,
            unified_session=False,
            disabled_skills=defaults.disabled_skills,
            session_ttl_minutes=defaults.session_ttl_minutes,
            tools_config=cfg.tools,
        )

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        sync_workspace_templates(self.workspace)
        self._configure_dream()
        self._configure_cron_callback()
        await self.cron.start()
        await self.agent._connect_mcp()
        self._tasks = [
            asyncio.create_task(self.agent.run()),
            asyncio.create_task(self._dispatch_outbound()),
        ]
        logger.info("Sendblue profile '{}' started at {}", self.profile_id, self.workspace)

    def _configure_dream(self) -> None:
        dream_cfg = self.root_config.agents.defaults.dream
        if dream_cfg.model_override:
            self.agent.dream.model = dream_cfg.model_override
        self.agent.dream.max_batch_size = dream_cfg.max_batch_size
        self.agent.dream.max_iterations = dream_cfg.max_iterations
        self.agent.dream.annotate_line_ages = dream_cfg.annotate_line_ages
        self.cron.register_system_job(CronJob(
            id="dream",
            name="dream",
            schedule=dream_cfg.build_schedule(self.root_config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        ))

    def _configure_cron_callback(self) -> None:
        async def on_cron_job(job: CronJob) -> str | None:
            if job.name == "dream":
                await self.agent.dream.run()
                return None

            reminder_note = (
                "[Scheduled Task] Timer finished.\n\n"
                f"Task '{job.name}' has been triggered.\n"
                f"Scheduled instruction: {job.payload.message}"
            )

            async def _silent(*_args, **_kwargs):
                pass

            chat_id = job.payload.to or self.profile.phone
            resp = await self.agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel="sendblue",
                chat_id=chat_id,
                on_progress=_silent,
            )
            response = resp.content if resp else ""
            if job.payload.deliver and chat_id and response:
                await self.bus.publish_outbound(OutboundMessage(
                    channel="sendblue",
                    chat_id=chat_id,
                    content=response,
                ))
            return response

        self.cron.on_job = on_cron_job

    async def stop(self) -> None:
        self._running = False
        for task in list(self._typing_tasks.values()):
            task.cancel()
        self._typing_tasks.clear()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.agent.close_mcp()
        self.cron.stop()
        self.agent.stop()
        self.sessions.flush_all()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self.start()
        if self.channel_config.typing_indicators:
            self._start_typing(msg.chat_id)
        await self.bus.publish_inbound(msg)

    def _start_typing(self, number: str) -> None:
        if number in self._typing_tasks and not self._typing_tasks[number].done():
            return
        self._typing_tasks[number] = asyncio.create_task(self._typing_loop(number))

    def _stop_typing(self, number: str) -> None:
        task = self._typing_tasks.pop(number, None)
        if task:
            task.cancel()

    async def _typing_loop(self, number: str) -> None:
        deadline = asyncio.get_running_loop().time() + self.channel_config.typing_max_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                await self.channel.send_typing_indicator(number)
                await asyncio.sleep(self.channel_config.typing_interval_seconds)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Sendblue typing indicator failed for {}: {}", number, exc)

    async def _dispatch_outbound(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            target = msg.chat_id or self.profile.phone
            self._stop_typing(target)
            await self.channel._send_outbound(msg, default_number=target)


class SendblueChannel(BaseChannel):
    """Sendblue webhook channel for iMessage/SMS."""

    name = "sendblue"
    display_name = "Sendblue"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SendblueConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = SendblueConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: SendblueConfig = config
        self._root_config: Config | None = None
        self._server: asyncio.Server | None = None
        self._dedupe: OrderedDict[str, None] = _load_dedupe()
        self._profiles_by_phone: dict[str, _ProfileRuntime] = {}
        self._client = httpx.AsyncClient(timeout=30)

    def set_root_config(self, config: Config) -> None:
        """Receive the loaded runtime config from ChannelManager."""
        self._root_config = config

    def is_allowed(self, sender_id: str) -> bool:
        allow = [_normalize_phone(item) for item in self.config.allow_from]
        if not allow:
            logger.warning("{}: allow_from is empty — all access denied", self.name)
            return False
        if "*" in allow:
            return True
        return _normalize_phone(sender_id) in allow

    async def start(self) -> None:
        if not self._root_config:
            raise RuntimeError("Sendblue channel requires root config")
        if not self.config.api_key_id or not self.config.api_secret_key:
            raise RuntimeError("Sendblue apiKeyId/apiSecretKey are required")
        if not self.config.from_number:
            raise RuntimeError("Sendblue fromNumber is required")

        self._init_profiles()
        await asyncio.gather(
            *(profile.start() for profile in self._profiles_by_phone.values()),
            return_exceptions=False,
        )
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_http,
            self.config.host,
            self.config.port,
        )
        logger.info(
            "Sendblue webhook listening at http://{}:{}{}",
            self.config.host,
            self.config.port,
            self.config.webhook_path,
        )
        async with self._server:
            await self._server.serve_forever()

    def _init_profiles(self) -> None:
        assert self._root_config is not None
        if not self.config.profiles:
            default_profile = SendblueProfileConfig(
                phone="",
                workspace=str(Path.home() / ".nanobot" / "profiles" / "default"),
                composio_user_id="default",
            )
            self.config.profiles = {"default": default_profile}

        for profile_id, profile in self.config.profiles.items():
            phone = _normalize_phone(profile.phone)
            if not phone:
                continue
            self._profiles_by_phone[phone] = _ProfileRuntime(
                profile_id=profile_id,
                profile=profile,
                root_config=self._root_config,
                channel_config=self.config,
                channel=self,
            )

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await asyncio.gather(
            *(profile.stop() for profile in self._profiles_by_phone.values()),
            return_exceptions=True,
        )
        await self._client.aclose()

    async def send(self, msg: OutboundMessage) -> None:
        await self._send_outbound(msg, default_number=msg.chat_id)

    async def send_typing_indicator(self, number: str) -> None:
        payload = {
            "from_number": self.config.from_number,
            "number": number,
        }
        await self._client.post(
            f"{self.config.api_base.rstrip('/')}/api/send-typing-indicator",
            headers=self._auth_headers(),
            json=payload,
        )

    async def _send_outbound(self, msg: OutboundMessage, *, default_number: str) -> None:
        number = _normalize_phone(msg.chat_id or default_number)
        if not number:
            logger.warning("Sendblue outbound missing recipient")
            return
        chunks = split_message(msg.content or "", SENDBLUE_MAX_MESSAGE_LEN) or [""]
        media = list(msg.media or [])
        if not media and not any(chunk.strip() for chunk in chunks):
            return

        for idx, chunk in enumerate(chunks):
            payload: dict[str, Any] = {
                "from_number": self.config.from_number,
                "number": number,
                "content": chunk,
            }
            if self.config.status_callback:
                payload["status_callback"] = self.config.status_callback
            if idx == 0 and media:
                first_media = media.pop(0)
                if first_media.startswith("http://") or first_media.startswith("https://"):
                    payload["media_url"] = first_media
            await self._post_message(payload)

        for media_url in media:
            if not (media_url.startswith("http://") or media_url.startswith("https://")):
                logger.warning("Sendblue media must be a public URL, skipping {}", media_url)
                continue
            await self._post_message({
                "from_number": self.config.from_number,
                "number": number,
                "media_url": media_url,
            })

    async def _post_message(self, payload: dict[str, Any]) -> None:
        resp = await self._client.post(
            f"{self.config.api_base.rstrip('/')}/api/send-message",
            headers=self._auth_headers(),
            json=payload,
        )
        resp.raise_for_status()

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "sb-api-key-id": self.config.api_key_id,
            "sb-api-secret-key": self.config.api_secret_key,
        }

    async def _handle_http(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request = await asyncio.wait_for(
                self._read_request(reader),
                timeout=_READ_TIMEOUT_SECONDS,
            )
            status, body = await self._handle_webhook_request(*request)
        except Exception as exc:
            logger.warning("Sendblue webhook request failed: {}", exc)
            status, body = 500, {"ok": False}
        await self._write_response(writer, status, body)

    async def _read_request(
        self,
        reader: asyncio.StreamReader,
    ) -> tuple[str, str, dict[str, str], bytes]:
        head = await reader.readuntil(b"\r\n\r\n")
        header_text = head.decode("utf-8", errors="replace")
        lines = header_text.split("\r\n")
        method, target, *_ = lines[0].split(" ")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0") or "0")
        body = await reader.readexactly(length) if length else b""
        return method, target, headers, body

    async def _handle_webhook_request(
        self,
        method: str,
        target: str,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, dict[str, Any]]:
        parsed = urlsplit(target)
        if method.upper() != "POST" or parsed.path != self.config.webhook_path:
            return 404, {"ok": False}
        if not self._verify_secret(headers, parsed.query):
            return 401, {"ok": False}
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return 400, {"ok": False}

        await self._handle_payload(payload)
        return 200, {"ok": True}

    def _verify_secret(self, headers: dict[str, str], query: str) -> bool:
        expected = self.config.webhook_secret
        if not expected:
            return True
        candidates = {
            headers.get("x-sendblue-secret", ""),
            headers.get("sendblue-secret", ""),
            headers.get("x-webhook-secret", ""),
            headers.get("x-sendblue-webhook-secret", ""),
        }
        query_secret = parse_qs(query).get("secret", [""])[0]
        candidates.add(query_secret)
        return expected in candidates

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        if payload.get("is_outbound") and not self.config.process_outbound_webhooks:
            return
        status = str(payload.get("status") or "").upper()
        if status and status != "RECEIVED":
            return

        handle = str(payload.get("message_handle") or "")
        if handle:
            if handle in self._dedupe:
                return
            self._dedupe[handle] = None
            while len(self._dedupe) > _DEDUP_MAX:
                self._dedupe.popitem(last=False)
            _save_dedupe(self._dedupe)

        sender = _normalize_phone(payload.get("from_number") or payload.get("number"))
        if not sender:
            return
        profile = self._profiles_by_phone.get(sender)
        if not profile:
            if self.config.deny_message and self.is_allowed(sender):
                await self._send_outbound(
                    OutboundMessage(
                        channel=self.name,
                        chat_id=sender,
                        content=self.config.deny_message,
                    ),
                    default_number=sender,
                )
            return
        if not self.is_allowed(sender):
            return

        content = str(payload.get("content") or "")
        media_url = str(payload.get("media_url") or "").strip()
        if media_url:
            content = f"{content}\n\n[Sendblue media] {media_url}".strip()
        msg = InboundMessage(
            channel=self.name,
            sender_id=sender,
            chat_id=sender,
            content=content,
            media=[],
            metadata={"sendblue": payload},
            session_key_override=f"sendblue:{sender}",
        )
        await profile.publish_inbound(msg)

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        body: dict[str, Any],
    ) -> None:
        reason = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            500: "Internal Server Error",
        }.get(status, "OK")
        raw = json.dumps(body).encode("utf-8")
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(raw)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8") + raw
        writer.write(response)
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
