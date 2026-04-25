"""Sendblue iMessage channel with per-sender profile isolation."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, available_timezones

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
from nanobot.cron.types import CronJob, CronPayload, CronSchedule
from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import split_message, sync_workspace_templates

SENDBLUE_MAX_MESSAGE_LEN = 18_500  # Sendblue limit is 18,996; keep headroom.
_DEDUP_MAX = 5000
_READ_TIMEOUT_SECONDS = 5
_ONBOARDING_FILE = "onboarding.json"
_MUFFS_START = "<!-- muffs-onboarding:start -->"
_MUFFS_END = "<!-- muffs-onboarding:end -->"
_ONBOARDING_COMPLETE = "complete"
_MORNING_DIGEST_ID = "morning-digest"


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


def _replace_marked_section(existing: str, section: str) -> str:
    block = f"{_MUFFS_START}\n{section.strip()}\n{_MUFFS_END}"
    if _MUFFS_START in existing and _MUFFS_END in existing:
        before, rest = existing.split(_MUFFS_START, 1)
        _, after = rest.split(_MUFFS_END, 1)
        return f"{before.rstrip()}\n\n{block}\n{after.lstrip()}".rstrip() + "\n"
    return f"{existing.rstrip()}\n\n{block}\n" if existing.strip() else f"{block}\n"


def _clean_answer(text: str, *, default: str = "") -> str:
    value = " ".join((text or "").strip().split())
    return value or default


def _is_yes(text: str) -> bool:
    return _clean_answer(text).lower() in {"y", "yes", "yeah", "yep", "sure", "ok", "okay", "please", "do it"}


def _is_no(text: str) -> bool:
    return _clean_answer(text).lower() in {"n", "no", "nah", "nope", "skip", "not now"}


def _parse_digest_time(text: str) -> tuple[int, int, str]:
    raw = _clean_answer(text, default="9am").lower().replace(".", "")
    import re

    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", raw)
    if not match:
        return 9, 0, "9:00 AM"
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    suffix = match.group(3)
    if suffix == "pm" and hour != 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    hour = max(0, min(hour, 23))
    minute = max(0, min(minute, 59))
    hour_12 = hour % 12 or 12
    display = f"{hour_12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
    return hour, minute, display


def _normalize_timezone(text: str, default_tz: str) -> str:
    value = _clean_answer(text)
    aliases = {
        "est": "America/New_York",
        "edt": "America/New_York",
        "eastern": "America/New_York",
        "eastern time": "America/New_York",
        "cst": "America/Chicago",
        "central": "America/Chicago",
        "mst": "America/Denver",
        "mountain": "America/Denver",
        "pst": "America/Los_Angeles",
        "pdt": "America/Los_Angeles",
        "pacific": "America/Los_Angeles",
    }
    key = value.lower()
    tz = aliases.get(key, value or default_tz)
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        close = next(
            (item for item in available_timezones() if item.lower().endswith("/" + key.replace(" ", "_"))),
            "",
        )
        return close or default_tz


class _SendblueOnboarding:
    """Deterministic per-profile onboarding flow for Sendblue users."""

    def __init__(self, runtime: "_ProfileRuntime") -> None:
        self.runtime = runtime
        self.path = runtime.workspace / _ONBOARDING_FILE

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("Sendblue onboarding: failed to read {}", self.path)
            return {}

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def is_complete(self) -> bool:
        return self.load().get("step") == _ONBOARDING_COMPLETE

    async def handle(self, msg: InboundMessage) -> bool:
        text = _clean_answer(msg.content)
        lowered = text.lower()
        state = self.load()

        if lowered == "/onboard":
            state = self._initial_state()
            self.save(state)
            await self._send(msg.chat_id, "What's your name?")
            return True
        if lowered in {"/skip", "skip onboarding"}:
            state = {**self._initial_state(), "step": _ONBOARDING_COMPLETE, "user_name": "there", "assistant_name": "Muffs"}
            self._persist_profile_files(state)
            self.save(state)
            await self._send(msg.chat_id, self._tool_connection_offer())
            return True
        if lowered == "/cancel" and state.get("step") != _ONBOARDING_COMPLETE:
            await self._send(msg.chat_id, "Onboarding is still needed before normal chat. Text /skip to use defaults.")
            return True

        if state.get("step") == _ONBOARDING_COMPLETE:
            return False

        if not state:
            state = self._initial_state()
            self.save(state)
            await self._send(msg.chat_id, "What's your name?")
            return True

        step = state.get("step", "ask_user_name")
        if step == "ask_user_name":
            state["user_name"] = text or "there"
            state["step"] = "ask_assistant_name"
            self.save(state)
            await self._send(
                msg.chat_id,
                "I'm Muffs, your personal fun assistant. Do you want to call me anything else?",
            )
            return True

        if step == "ask_assistant_name":
            if text and not _is_no(text):
                state["assistant_name"] = text
            state["step"] = "offer_digest"
            self.save(state)
            await self._send(
                msg.chat_id,
                f"{state['assistant_name']} it is. Let me give you a quick feel for what I can do.\n\n"
                "- I can watch your inbox or calendar once you connect them.\n"
                "- I can help plan and organize your day.\n"
                "- I can set reminders for basically anything.\n"
                "- I can research, answer questions, and keep track of useful context.\n\n"
                "Want me to set up a morning briefing/digest? I can research your interests and surface anything worth knowing every day before work.",
            )
            return True

        if step == "offer_digest":
            if _is_yes(text):
                state["step"] = "ask_digest_topics"
                self.save(state)
                await self._send(
                    msg.chat_id,
                    "What topics do you want covered? It can be anything: tech news, finance, sports, research, interesting fact of the day, a Bible verse, a devotional, or whatever else.",
                )
                return True
            state["digest_enabled"] = False
            state["step"] = _ONBOARDING_COMPLETE
            self._persist_profile_files(state)
            self.save(state)
            await self._send(msg.chat_id, "All set. " + self._tool_connection_offer())
            return True

        if step == "ask_digest_topics":
            state["digest_enabled"] = True
            state["digest_topics"] = text or "useful news, schedule, and interesting things worth knowing"
            state["step"] = "ask_digest_time"
            self.save(state)
            await self._send(msg.chat_id, "What time do you want it delivered each morning?")
            return True

        if step == "ask_digest_time":
            hour, minute, display = _parse_digest_time(text)
            state["digest_hour"] = hour
            state["digest_minute"] = minute
            state["digest_time_display"] = display
            state["step"] = "ask_timezone"
            self.save(state)
            await self._send(msg.chat_id, "What timezone should I use? For example: EST, America/New_York, or Pacific.")
            return True

        if step == "ask_timezone":
            tz = _normalize_timezone(text, self.runtime.root_config.agents.defaults.timezone)
            state["timezone"] = tz
            state["step"] = _ONBOARDING_COMPLETE
            self._persist_profile_files(state)
            self._upsert_digest_job(state, msg.chat_id)
            self.save(state)
            topics = state.get("digest_topics", "")
            await self._send(
                msg.chat_id,
                f"Ok, all set. Your digest will cover {topics} and will hit your messages every morning at "
                f"{state.get('digest_time_display', '9:00 AM')} {tz}. First one is tomorrow.\n\n"
                + self._tool_connection_offer(),
            )
            return True

        state["step"] = "ask_user_name"
        self.save(state)
        await self._send(msg.chat_id, "What's your name?")
        return True

    def _initial_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "step": "ask_user_name",
            "assistant_name": "Muffs",
            "started_at": datetime.now().isoformat(),
        }

    async def _send(self, chat_id: str, content: str) -> None:
        await self.runtime.channel._send_outbound(
            OutboundMessage(channel="sendblue", chat_id=chat_id, content=content),
            default_number=chat_id,
        )

    def _tool_connection_offer(self) -> str:
        return (
            "By the way, if you ever want to connect Gmail, Calendar, Notion, GitHub, or something else, "
            "I can pull those into your digest or use them generally. Just tell me what you want to connect."
        )

    def _persist_profile_files(self, state: dict[str, Any]) -> None:
        self.runtime.workspace.mkdir(parents=True, exist_ok=True)
        self._write_soul(state)
        self._write_user(state)
        self._write_memory(state)

    def _write_soul(self, state: dict[str, Any]) -> None:
        assistant_name = state.get("assistant_name") or "Muffs"
        section = f"""# Muffs Personality

- Assistant display name: {assistant_name}
- Default identity: a personal, fun assistant inspired by Muffs, the user's cat.
- Be warm, practical, direct, and a little playful without being long-winded.
- Help the user plan their day, remember commitments, answer questions, research useful information, and connect tools when asked.
- When the user asks to connect Gmail, Calendar, Notion, GitHub, or another app, use Composio connection tools to generate an auth link."""
        path = self.runtime.workspace / "SOUL.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(_replace_marked_section(existing, section), encoding="utf-8")

    def _write_user(self, state: dict[str, Any]) -> None:
        topics = state.get("digest_topics") or "not configured"
        digest = "enabled" if state.get("digest_enabled") else "disabled"
        section = f"""# Sendblue Profile

- User name: {state.get("user_name") or "there"}
- Assistant name preference: {state.get("assistant_name") or "Muffs"}
- Timezone: {state.get("timezone") or self.runtime.root_config.agents.defaults.timezone}
- Morning digest: {digest}
- Digest topics: {topics}
- Communication style: casual, concise, useful, and friendly."""
        path = self.runtime.workspace / "USER.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(_replace_marked_section(existing, section), encoding="utf-8")

    def _write_memory(self, state: dict[str, Any]) -> None:
        memory_dir = self.runtime.workspace / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        path = memory_dir / "MEMORY.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        digest = "enabled" if state.get("digest_enabled") else "disabled"
        section = f"""# Muffs Onboarding Facts

- User's name is {state.get("user_name") or "there"}.
- Assistant display name is {state.get("assistant_name") or "Muffs"}.
- User timezone is {state.get("timezone") or self.runtime.root_config.agents.defaults.timezone}.
- Morning digest is {digest}.
- Digest topics: {state.get("digest_topics") or "not configured"}."""
        path.write_text(_replace_marked_section(existing, section), encoding="utf-8")

    def _upsert_digest_job(self, state: dict[str, Any], chat_id: str) -> None:
        if not state.get("digest_enabled"):
            return
        hour = int(state.get("digest_hour", 9))
        minute = int(state.get("digest_minute", 0))
        tz = state.get("timezone") or self.runtime.root_config.agents.defaults.timezone
        message = (
            f"Create a concise morning briefing for {state.get('user_name') or 'the user'}.\n"
            f"Assistant name: {state.get('assistant_name') or 'Muffs'}.\n"
            f"Topics to cover: {state.get('digest_topics')}.\n"
            "Use connected Composio tools such as calendar or Gmail if available. "
            "If those tools are not connected, rely on available research/web context and briefly mention that Gmail or Calendar can be connected later. "
            "Keep it useful, skimmable, and ready to send as an iMessage."
        )
        schedule = CronSchedule(kind="cron", expr=f"{minute} {hour} * * *", tz=tz)
        existing = next(
            (job for job in self.runtime.cron.list_jobs(include_disabled=True) if job.id == _MORNING_DIGEST_ID or job.name == _MORNING_DIGEST_ID),
            None,
        )
        if existing:
            self.runtime.cron.update_job(
                existing.id,
                name=_MORNING_DIGEST_ID,
                schedule=schedule,
                message=message,
                deliver=True,
                channel="sendblue",
                to=chat_id,
            )
            return
        job = CronJob(
            id=_MORNING_DIGEST_ID,
            name=_MORNING_DIGEST_ID,
            schedule=schedule,
            payload=CronPayload(kind="agent_turn", message=message, deliver=True, channel="sendblue", to=chat_id),
        )
        # Use the public update path when possible, but keep the stable id for
        # repeatable per-profile updates and easy inspection on disk.
        store = self.runtime.cron._load_store()
        now = int(datetime.now().timestamp() * 1000)
        job.created_at_ms = now
        job.updated_at_ms = now
        store.jobs = [item for item in store.jobs if item.id != _MORNING_DIGEST_ID and item.name != _MORNING_DIGEST_ID]
        store.jobs.append(job)
        self.runtime.cron._recompute_next_runs()
        self.runtime.cron._save_store()
        self.runtime.cron._arm_timer()


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
        self.onboarding = _SendblueOnboarding(self)
        self.provider = self._make_provider()
        self.agent = self._make_agent()
        self._tasks: list[asyncio.Task] = []
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def _profile_config(self) -> Config:
        cfg = self.root_config.model_copy(deep=True)
        cfg.agents.defaults.workspace = str(self.workspace)
        composio = cfg.tools.composio
        composio.user_id = self.profile.composio_user_id or self.profile_id
        if composio.enabled and composio.api_key and composio.mcp_server_id:
            base = composio.base_url.rstrip("/")
            server_id = composio.mcp_server_id.strip("/")
            cfg.tools.mcp_servers = dict(cfg.tools.mcp_servers)
            cfg.tools.mcp_servers["composio"] = MCPServerConfig(
                type="streamableHttp",
                url=f"{base}/{server_id}?user_id={composio.user_id}",
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

    async def handle_inbound(self, msg: InboundMessage) -> None:
        await self.start()
        if await self.onboarding.handle(msg):
            return
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
        if hasattr(profile, "handle_inbound"):
            await profile.handle_inbound(msg)
        else:
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
