"""Wire scheduled turns and system jobs into the Gateway's cron service."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol, cast

from loguru import logger

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.service import CronJobSkippedError
from nanobot.cron.session_turns import is_bound_cron_job
from nanobot.cron.types import CronJob, CronPayload, CronRunResult, CronSchedule
from nanobot.llm_usage.context import llm_usage_source
from nanobot.session.keys import HEARTBEAT_SESSION_KEY
from nanobot.utils.evaluator import evaluate_response, resolve_evaluator_prompt
from nanobot.webui.sidebar_state import ensure_webui_session_archives

if TYPE_CHECKING:
    from rich.console import Console

    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.mcp import MCPProvider
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config
    from nanobot.cron.service import CronService


class _HeartbeatDelivery(Protocol):
    async def __call__(
        self, msg: OutboundMessage, /, *, record: bool, session_key: str, session_generation: str,
    ) -> None: ...


def _advance_dream_cursor_if_behind(memory: MemoryStore) -> None:
    latest = memory.get_latest_cursor()
    if memory.get_last_dream_cursor() < latest:
        memory.set_last_dream_cursor(latest)


def _commit_dream_changes(memory: MemoryStore) -> str | None:
    if not memory.git.is_initialized() or not (diff_body := memory.dream_content_diff()):
        return None
    message = memory.build_dream_commit_message("dream: periodic memory consolidation", diff_body)
    return memory.git.auto_commit(message)


_HEARTBEAT_PREAMBLE = (
    "[Your response will be delivered directly to the user's messaging app. "
    "Output ONLY the final user-facing message. Never reference internal "
    "files (HEARTBEAT.md, AWARENESS.md, etc.), your instructions, or your "
    "decision process. If nothing needs reporting, respond with just "
    "'All clear.' and nothing else.]\n\n"
)


def _heartbeat_has_active_tasks(content: str) -> bool:
    in_comment = False
    in_active_section = False
    for line in content.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if not stripped or stripped.startswith("#"):
            if stripped.startswith("##") and not stripped.startswith("###"):
                heading = stripped.lstrip("#").strip().lower()
                in_active_section = heading.startswith("active tasks")
        elif stripped.startswith("<!--"):
            in_comment = "-->" not in stripped[4:]
        elif in_active_section:
            return True
    return False


def _pick_heartbeat_target_from_sessions(
    *,
    enabled_channels: Iterable[str],
    sessions: Iterable[dict[str, Any]],
    archived_keys: Iterable[str],
) -> tuple[str, str]:
    enabled, archived = set(enabled_channels), set(archived_keys)
    for item in sessions:
        key = item.get("key") or ""
        if key in archived or ":" not in key:
            continue
        channel, chat_id = key.split(":", 1)
        if channel not in {"cli", "system"} and channel in enabled and chat_id:
            return channel, chat_id
    return "cli", "direct"


async def _silent(*_args: Any, **_kwargs: Any) -> None:
    pass


async def _run_dream(agent: AgentLoop, mcp_provider: MCPProvider) -> None:
    store = agent.context.memory
    try:
        result = store.build_dream_prompt()
        if result is None:
            logger.info("Dream: nothing to process")
            return
        prompt, last_cursor = result
        key = MemoryStore.dream_session_key()
        runtime = agent.dream_runtime()
        await mcp_provider.connect()
        response = await agent.process_direct(
            prompt,
            session_key=key,
            ephemeral=True,
            tools=store.build_dream_tools(),
            on_progress=_silent,
            runtime=runtime,
        )
        # The actual file delta grounds the audit record, but only normal
        # completion decides whether this history batch is done.
        diff_body = store.dream_content_diff()
        if MemoryStore.dream_run_completed(response):
            store.set_last_dream_cursor(last_cursor)
            note = ", " if diff_body else " with no memory changes; "
            logger.info("Dream cron job completed{}cursor advanced to {}", note, last_cursor)
        else:
            logger.warning(
                "Dream cron job did not complete ({}); cursor remains at {}",
                MemoryStore.dream_incompletion_reason(response),
                store.get_last_dream_cursor(),
            )
    except Exception:
        logger.exception("Dream cron job failed")
    finally:
        if sha := _commit_dream_changes(store):
            logger.info("Dream commit: {}", sha)
        store.compact_history()
        await agent.sessions.state.prune_dream_sessions()


async def _run_heartbeat(
    config: Config,
    agent: AgentLoop,
    mcp_provider: MCPProvider,
    channels: ChannelManager,
    deliver: _HeartbeatDelivery,
) -> str | None:
    try:
        content = (config.workspace_path / "HEARTBEAT.md").read_text(encoding="utf-8")
    except OSError:
        logger.debug("Heartbeat: HEARTBEAT.md missing")
        return None
    if not _heartbeat_has_active_tasks(content):
        logger.debug("Heartbeat: HEARTBEAT.md has no active tasks")
        return None

    state = agent.sessions.state
    archived = await ensure_webui_session_archives(state)
    channel, chat_id = _pick_heartbeat_target_from_sessions(
        enabled_channels=channels.enabled_channels,
        sessions=await state.list_sessions(),
        archived_keys=archived,
    )
    if channel == "cli":
        return None
    delivery_key = f"{channel}:{chat_id}"
    delivery_session = await state.read(delivery_key)
    if delivery_session is None:
        return None
    delivery_generation = delivery_session.generation
    prompt = (
        _HEARTBEAT_PREAMBLE
        + f"You are executing periodic heartbeat tasks. Read the active tasks below, perform each one, and report what you did:\n\n{content}"
    )

    # Internal check: the message tool must not bypass post-run evaluation.
    tool = agent.tools.get("message")
    message_tool = tool if isinstance(tool, MessageTool) else None
    token = message_tool.set_suppress_delivery(True) if message_tool is not None else None
    try:
        await mcp_provider.connect()
        response = await agent.process_direct(
            prompt, session_key=HEARTBEAT_SESSION_KEY, channel=channel, chat_id=chat_id, on_progress=_silent,
        )
    finally:
        if message_tool is not None and token is not None:
            message_tool.reset_suppress_delivery(token)

    if not response or not response.content:
        return None

    # Fail closed: stay silent on evaluator failure instead of notifying.
    evaluator_prompt = resolve_evaluator_prompt(config.workspace_path)
    with llm_usage_source("cron"):
        should_notify = await evaluate_response(
            response=response.content,
            task_context=prompt,
            provider=agent.provider,
            model=agent.model,
            evaluator_prompt=evaluator_prompt,
            default_notify=False,
        )
    if should_notify:
        logger.info("Heartbeat: completed, delivering response")
        await deliver(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response.content),
            record=True,
            session_key=delivery_key,
            session_generation=delivery_generation,
        )
    else:
        logger.info("Heartbeat: silenced by post-run evaluation")
    return response.content


def configure_gateway_jobs(
    cron: CronService,
    *,
    config: Config,
    agent: AgentLoop,
    mcp_provider: MCPProvider,
    channels: ChannelManager,
    deliver: _HeartbeatDelivery,
    console: Console,
) -> None:
    """Set job policy and reconcile built-ins before the scheduler starts."""
    async def on_job(job: CronJob) -> str | CronRunResult | None:
        if job.name == "dream":
            await _run_dream(agent, mcp_provider)
            return None
        if job.name == "heartbeat":
            return await _run_heartbeat(config, agent, mcp_provider, channels, deliver)
        if is_bound_cron_job(job):
            return await run_bound_cron_job(job, agent=agent, cron=cron)
        reason = "unbound agent cron job must be recreated from a chat session"
        logger.warning("Cron: skipped unbound agent job '{}' ({}): {}", job.name, job.id, reason)
        raise CronJobSkippedError(reason)

    cron.on_job = on_job
    heartbeat = config.gateway.heartbeat
    dream = config.agents.defaults.dream
    if heartbeat.enabled:
        console.print(f"[green]✓[/green] Heartbeat: every {heartbeat.interval_s}s")
    else:
        console.print("[yellow]✗[/yellow] Heartbeat: disabled")

    if dream.enabled:
        cron.register_system_job(CronJob(
            id="dream", name="dream",
            schedule=dream.build_schedule(config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        ))
        console.print(f"[green]✓[/green] Dream: {dream.describe_schedule()}")
    else:
        console.print("[yellow]○[/yellow] Dream: disabled")
        # Cursor repair must not depend on a healthy cron store.
        _advance_dream_cursor_if_behind(agent.context.memory)
        cron.remove_system_job("dream")

    if heartbeat.enabled:
        cron.register_system_job(CronJob(
            id="heartbeat", name="heartbeat",
            schedule=CronSchedule(kind="every", every_ms=heartbeat.interval_s * 1000,
                                  tz=config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        ))
    else:
        cron.remove_system_job("heartbeat")

    count = cast(int, cron.status()["jobs"])
    if count > 0:
        console.print(f"[green]✓[/green] Cron: {count} scheduled jobs")
