"""Gateway runtime bootstrap and orchestration."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

from rich.console import Console

from nanobot import __logo__
from nanobot.app.prompts import (
    build_cron_execution_message,
    build_heartbeat_execution_message,
    should_deliver_heartbeat_response,
)
from nanobot.app.runtime import build_agent_runtime, load_runtime_config, make_provider
from nanobot.utils.helpers import sync_workspace_templates

if TYPE_CHECKING:
    from nanobot.config.schema import Config


class _GatewayInstanceLock:
    """Best-effort single-instance lock for gateway mode."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("gateway lock is already held") from exc
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(str(os.getpid()))
        self._fh.flush()

    def release(self) -> None:
        if not self._fh:
            return
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        self._fh.close()
        self._fh = None


class _TaskSupervisor:
    """Track failure counts for a supervised async task with exponential backoff."""

    MAX_CONSECUTIVE_FAILURES = 5
    INITIAL_BACKOFF_S = 1.0
    MAX_BACKOFF_S = 60.0
    MIN_HEALTHY_DURATION_S = 30.0

    def __init__(self, name: str):
        self.name = name
        self.consecutive_failures = 0
        self.backoff_s = self.INITIAL_BACKOFF_S
        self._started_at: float = 0.0

    def mark_started(self) -> None:
        self._started_at = time.monotonic()

    def record_failure(self) -> None:
        elapsed = time.monotonic() - self._started_at if self._started_at else 0.0
        if elapsed >= self.MIN_HEALTHY_DURATION_S:
            self.consecutive_failures = 1
            self.backoff_s = self.INITIAL_BACKOFF_S
        else:
            self.consecutive_failures += 1
            self.backoff_s = min(self.backoff_s * 2, self.MAX_BACKOFF_S)

    def should_escalate(self) -> bool:
        return self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES


def _gateway_lock_path() -> Path:
    from nanobot.config.loader import get_config_path

    return get_config_path().parent / "gateway.lock"


def _looks_like_gateway_command(command: str) -> bool:
    lowered = command.lower()
    return bool(
        re.search(r"(^|\s)(?:\S*/)?nanobot(?:\.py)?\s+gateway(?:\s|$)", lowered)
        or re.search(
            r"(^|\s)(?:\S*/)?python(?:\d+(?:\.\d+)*)?\s+-m\s+nanobot(?:\.cli\.commands)?\s+gateway(?:\s|$)",
            lowered,
        )
    )


def _find_other_gateway_processes() -> list[tuple[int, str]]:
    """Find other local nanobot gateway processes by scanning the process table."""
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return []

    current_pid = os.getpid()
    matches: list[tuple[int, str]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        command = parts[1].strip()
        if pid == current_pid or not _looks_like_gateway_command(command):
            continue
        matches.append((pid, command))
    return matches


_RESTART_MARKER = Path.home() / ".nanobot" / "restart_marker.json"


def _write_restart_marker(reason: str) -> None:
    """Write a restart marker so the next startup can notify the admin."""
    _RESTART_MARKER.parent.mkdir(parents=True, exist_ok=True)
    _RESTART_MARKER.write_text(
        json.dumps({"reason": reason, "ts": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )


def _read_and_clear_restart_marker() -> dict | None:
    """Read and delete the restart marker if present."""
    if not _RESTART_MARKER.exists():
        return None
    try:
        data = json.loads(_RESTART_MARKER.read_text(encoding="utf-8"))
        _RESTART_MARKER.unlink(missing_ok=True)
        return data
    except Exception:
        _RESTART_MARKER.unlink(missing_ok=True)
        return None


async def _send_telegram_direct(token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message directly via HTTP (no bus/channel dependency)."""
    try:
        import httpx

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={
                "chat_id": int(chat_id),
                "text": text,
                "parse_mode": "HTML",
            })
            return resp.status_code == 200
    except Exception:
        return False


def _get_telegram_admin_target(config: Any) -> tuple[str, str] | None:
    """Extract (token, admin_chat_id) from Telegram channel config."""
    tg_cfg = getattr(config.channels, "telegram", None)
    if tg_cfg is None:
        return None
    if isinstance(tg_cfg, dict):
        token = tg_cfg.get("token", "")
        allow_from = tg_cfg.get("allow_from", [])
    else:
        token = getattr(tg_cfg, "token", "")
        allow_from = getattr(tg_cfg, "allow_from", [])
    if not token or not allow_from:
        return None
    return token, str(allow_from[0])


def run_gateway(
    *,
    port: int | None,
    workspace: str | None,
    verbose: bool,
    config_path: str | None,
    console: Console | None = None,
    restart_args: Sequence[str] | None = None,
    load_config_fn: Callable[[str | None, str | None], Config] | None = None,
    sync_templates_fn: Callable[[Path], Any] | None = None,
    provider_factory: Callable[[Config], Any] | None = None,
    find_other_gateway_processes: Callable[[], list[tuple[int, str]]] | None = None,
    gateway_lock_cls: Callable[[Path], Any] | None = None,
    gateway_lock_path_factory: Callable[[], Path] | None = None,
) -> None:
    """Run the nanobot gateway with overridable runtime dependencies."""
    from loguru import logger

    from nanobot.bus.events import OutboundMessage
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.types import CronJob
    from nanobot.debug.runtime_diagnostics import build_report, render_failure_brief
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.repo_sync.service import RepoSyncWatcher
    from nanobot.session.manager import SessionManager

    # --- file logging ---------------------------------------------------
    log_dir = Path.home() / ".nanobot" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "nanobot.log",
        rotation="5 MB",
        retention=3,
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )
    # --------------------------------------------------------------------

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console = console or Console()
    restart_argv = list(restart_args or sys.argv[1:])

    if load_config_fn is None:
        def load_config_fn(config_path_arg: str | None, workspace_arg: str | None) -> Config:
            return load_runtime_config(config_path_arg, workspace_arg, console=console)
    if sync_templates_fn is None:
        sync_templates_fn = sync_workspace_templates
    if provider_factory is None:
        def provider_factory(config_obj: Config) -> Any:
            return make_provider(config_obj, console=console)
    if find_other_gateway_processes is None:
        find_other_gateway_processes = _find_other_gateway_processes
    if gateway_lock_cls is None:
        gateway_lock_cls = _GatewayInstanceLock
    if gateway_lock_path_factory is None:
        gateway_lock_path_factory = _gateway_lock_path

    config = load_config_fn(config_path, workspace)
    effective_port = port if port is not None else config.gateway.port
    if others := find_other_gateway_processes():
        console.print("[red]Another nanobot gateway instance is already running.[/red]")
        for pid, command in others:
            console.print(f"  PID {pid}: {command}")
        raise SystemExit(1)

    instance_lock = gateway_lock_cls(gateway_lock_path_factory())
    try:
        instance_lock.acquire()
    except RuntimeError as exc:
        console.print("[red]Another nanobot gateway instance already holds the gateway lock.[/red]")
        raise SystemExit(1) from exc

    try:
        if config.agents.defaults.should_warn_deprecated_memory_window:
            console.print(
                "[yellow]Hint:[/yellow] Detected deprecated `memoryWindow` without "
                "`contextWindowTokens`. `memoryWindow` is ignored; run "
                "[cyan]nanobot onboard[/cyan] to refresh your config template."
            )
        console.print(f"{__logo__} Starting nanobot gateway on port {effective_port}...")
        sync_templates_fn(config.workspace_path)
        session_manager = SessionManager(config.workspace_path)
        repo_sync_cfg = config.gateway.repo_sync
        legacy_repo_sync_marker = "__repo_sync__::"
        restart_requested = False
        escalate_to_process_restart = False

        async def request_restart() -> None:
            nonlocal restart_requested
            restart_requested = True

        bus = None

        async def _publish_auto_diagnosis(
            *,
            channel: str,
            chat_id: str,
            title: str,
            details: list[str],
            session_key: str | None = None,
        ) -> None:
            if not chat_id or channel == "cli" or bus is None:
                return
            try:
                report = build_report(
                    workspace=config.workspace_path,
                    limit=3,
                    session_key=session_key,
                )
                content = render_failure_brief(report, title=title, details=details)
            except Exception:
                logger.exception("Failed to build auto-diagnosis report")
                return
            await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=content))

        async def _publish_notice(
            *,
            channel: str,
            chat_id: str,
            title: str,
            details: list[str],
        ) -> None:
            if not chat_id or channel == "cli" or bus is None:
                return
            lines = [title.strip(), ""]
            lines.extend(f"- {detail}" for detail in details if detail)
            content = "\n".join(lines).rstrip() + "\n"
            await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=content))

        async def on_message_error(msg, error: Exception) -> None:
            """Deliver a concise auto-diagnosis for normal message failures."""
            if msg.channel == "cli":
                return
            await _publish_auto_diagnosis(
                channel=msg.channel,
                chat_id=msg.chat_id,
                title="nanobot auto-diagnosis: message failure",
                details=[
                    f"Session: `{msg.session_key}`",
                    f"Error: `{type(error).__name__}: {error}`",
                ],
                session_key=msg.session_key,
            )

        runtime = build_agent_runtime(
            config,
            provider_factory=provider_factory,
            session_manager=session_manager,
            restart_callback=request_restart,
            error_callback=on_message_error,
        )
        bus = runtime.bus
        provider = runtime.provider
        cron = runtime.cron
        agent = runtime.agent

        async def on_cron_job(job: CronJob) -> str | None:
            """Execute a cron job through the agent."""
            from nanobot.agent.tools.cron import CronTool
            from nanobot.agent.tools.message import MessageTool

            if hasattr(agent, "context") and hasattr(agent.context, "build_cron_prompt"):
                reminder_note = agent.context.build_cron_prompt(job.name, job.payload.message)
            else:
                reminder_note = build_cron_execution_message(job.name, job.payload.message)

            async def _silent(*_args, **_kwargs):
                pass

            cron_tool = agent.tools.get("cron")
            cron_token = None
            if isinstance(cron_tool, CronTool):
                cron_token = cron_tool.set_cron_context(True)
            try:
                if hasattr(agent, "process_system_turn"):
                    response = await agent.process_system_turn(
                        reminder_note,
                        session_key=f"cron:{job.id}",
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to or "direct",
                        on_progress=_silent,
                        stateless=True,
                        model=getattr(agent, "automation_model", None),
                    )
                else:
                    response = await agent.process_direct(
                        content=reminder_note,
                        session_key=f"cron:{job.id}",
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to or "direct",
                        on_progress=_silent,
                    )
            finally:
                if isinstance(cron_tool, CronTool) and cron_token is not None:
                    cron_tool.reset_cron_context(cron_token)

            message_tool = agent.tools.get("message")
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return response

            if job.payload.deliver and job.payload.to and response:
                await bus.publish_outbound(
                    OutboundMessage(
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to,
                        content=response,
                    )
                )
            return response

        async def on_cron_error(job: CronJob, error: Exception) -> None:
            """Deliver a concise auto-diagnosis for cron failures."""
            if not (job.payload.deliver and job.payload.to):
                return
            await _publish_auto_diagnosis(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                title="nanobot auto-diagnosis: cron failure",
                details=[
                    f"Job: `{job.name}` (`{job.id}`)",
                    f"Error: `{type(error).__name__}: {error}`",
                ],
                session_key=f"cron:{job.id}",
            )

        cron.on_job = on_cron_job
        cron.on_error = on_cron_error

        legacy_repo_jobs = [
            job
            for job in cron.list_jobs(include_disabled=True)
            if job.payload.message.startswith(legacy_repo_sync_marker)
        ]
        if legacy_repo_jobs:
            for job in legacy_repo_jobs:
                cron.remove_job(job.id)
            console.print(
                f"[green]✓[/green] Removed {len(legacy_repo_jobs)} legacy repo sync cron job(s)"
            )

        channels = ChannelManager(config, bus)

        def _pick_heartbeat_target() -> tuple[str, str]:
            enabled = set(channels.enabled_channels)
            for item in session_manager.list_sessions():
                key = item.get("key") or ""
                if ":" not in key:
                    continue
                channel_name, chat_id = key.split(":", 1)
                if channel_name in {"cli", "system"}:
                    continue
                if channel_name in enabled and chat_id:
                    return channel_name, chat_id
            return "cli", "direct"

        async def on_heartbeat_execute(tasks: str) -> str:
            channel_name, chat_id = _pick_heartbeat_target()
            heartbeat_content = ""
            heartbeat_file = config.workspace_path / "HEARTBEAT.md"
            if heartbeat_file.exists():
                try:
                    heartbeat_content = heartbeat_file.read_text(encoding="utf-8")
                except Exception:
                    heartbeat_content = ""
            prompt = build_heartbeat_execution_message(tasks, heartbeat_content)

            async def _silent(*_args, **_kwargs):
                pass

            return await agent.process_system_turn(
                prompt,
                session_key="heartbeat",
                channel=channel_name,
                chat_id=chat_id,
                on_progress=_silent,
                stateless=True,
                model=agent.automation_model,
            )

        async def on_heartbeat_notify(response: str) -> None:
            if not should_deliver_heartbeat_response(response):
                return
            channel_name, chat_id = _pick_heartbeat_target()
            if channel_name == "cli":
                return
            await bus.publish_outbound(
                OutboundMessage(channel=channel_name, chat_id=chat_id, content=response)
            )

        async def on_heartbeat_error(phase: str, error: Exception) -> None:
            channel_name, chat_id = _pick_heartbeat_target()
            if channel_name == "cli":
                return
            await _publish_auto_diagnosis(
                channel=channel_name,
                chat_id=chat_id,
                title="nanobot auto-diagnosis: heartbeat failure",
                details=[
                    f"Phase: `{phase}`",
                    f"Error: `{type(error).__name__}: {error}`",
                ],
                session_key="heartbeat",
            )

        async def on_heartbeat_recovery(status: str, payload: dict[str, object]) -> None:
            channel_name, chat_id = _pick_heartbeat_target()
            if channel_name == "cli":
                return

            phase = str(payload.get("phase") or "decision")
            retry_delay = payload.get("retry_delay_s")
            retry_delay_text = f"{retry_delay}s" if retry_delay is not None else "unknown"
            latest_error = payload.get("latest_error") or payload.get("error")

            if status == "scheduled":
                await _publish_notice(
                    channel=channel_name,
                    chat_id=chat_id,
                    title="nanobot auto-recovery: heartbeat retry scheduled",
                    details=[
                        f"Phase: `{phase}`",
                        f"Retry delay: `{retry_delay_text}`",
                        "Transient heartbeat failure detected; one automatic retry has been scheduled.",
                    ],
                )
                return

            if status == "recovered":
                await _publish_notice(
                    channel=channel_name,
                    chat_id=chat_id,
                    title="nanobot auto-recovery: heartbeat recovered",
                    details=[
                        f"Phase: `{phase}`",
                        f"Retry delay: `{retry_delay_text}`",
                        "The automatic heartbeat retry succeeded; no manual action is needed right now.",
                    ],
                )
                return

            details = [
                f"Phase: `{phase}`",
                f"Retry delay: `{retry_delay_text}`",
            ]
            if latest_error:
                details.append(f"Latest error: `{latest_error}`")
            details.append(
                "The automatic heartbeat retry did not recover the failure; continue manual troubleshooting."
            )
            await _publish_notice(
                channel=channel_name,
                chat_id=chat_id,
                title="nanobot auto-recovery: heartbeat retry exhausted",
                details=details,
            )

        hb_cfg = config.gateway.heartbeat
        try:
            heartbeat_provider, heartbeat_model, _ = agent._resolve_provider_for_model(agent.automation_model)
        except Exception:
            heartbeat_provider, heartbeat_model = provider, agent.model
        heartbeat = HeartbeatService(
            workspace=config.workspace_path,
            provider=heartbeat_provider,
            model=heartbeat_model,
            on_execute=on_heartbeat_execute,
            on_notify=on_heartbeat_notify,
            on_error=on_heartbeat_error,
            on_recovery=on_heartbeat_recovery,
            interval_s=hb_cfg.interval_s,
            enabled=hb_cfg.enabled,
        )

        repo_sync_watcher: RepoSyncWatcher | None = None
        if repo_sync_cfg.enabled:
            repo_sync_watcher = RepoSyncWatcher(
                repo_path=repo_sync_cfg.repo_path,
                branch=repo_sync_cfg.branch,
                upstream_remote=repo_sync_cfg.upstream_remote,
                upstream_url=repo_sync_cfg.upstream_url,
                push_remote=repo_sync_cfg.push_remote,
                auto_push=repo_sync_cfg.auto_push,
                allow_dirty_worktree=repo_sync_cfg.allow_dirty_worktree,
                interval_s=repo_sync_cfg.watch_interval_s,
                sync_hour=repo_sync_cfg.sync_hour,
                run_on_start=repo_sync_cfg.run_on_start,
                ssh_command=repo_sync_cfg.ssh_command,
            )

        if channels.enabled_channels:
            console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
        else:
            console.print("[yellow]Warning: No channels enabled[/yellow]")

        cron_status = cron.status()
        if cron_status["jobs"] > 0:
            console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
        if repo_sync_watcher:
            console.print(f"[green]✓[/green] Repo sync watcher: every {repo_sync_cfg.watch_interval_s}s")
        console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

        async def run() -> None:
            nonlocal escalate_to_process_restart
            agent_task: asyncio.Task | None = None
            channels_task: asyncio.Task | None = None
            agent_sup = _TaskSupervisor("agent")
            channels_sup = _TaskSupervisor("channels")
            try:
                await cron.start()
                await heartbeat.start()
                if repo_sync_watcher:
                    await repo_sync_watcher.start()
                agent_task = asyncio.create_task(agent.run())
                agent_sup.mark_started()
                channels_task = asyncio.create_task(channels.start_all())
                channels_sup.mark_started()

                # Post-restart notification
                marker = _read_and_clear_restart_marker()
                if marker:
                    tg = _get_telegram_admin_target(config)
                    if tg:
                        reason = marker.get("reason", "unknown")
                        prev_ts = marker.get("ts", "")
                        await _send_telegram_direct(
                            tg[0], tg[1],
                            f"✅ <b>nanobot 已恢复运行</b>\n"
                            f"上次停机原因: {reason}\n"
                            f"停机时间: {prev_ts}\n"
                            f"恢复时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                        )

                while True:
                    if restart_requested:
                        reason = "user-requested restart (/restart command)"
                        _write_restart_marker(reason)
                        tg = _get_telegram_admin_target(config)
                        if tg:
                            await _send_telegram_direct(tg[0], tg[1], "🔄 <b>nanobot 正在重启</b>\n原因: 用户请求重启")
                        await asyncio.sleep(0.2)
                        break
                    done, _ = await asyncio.wait(
                        {agent_task, channels_task},
                        timeout=0.5,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        continue

                    should_break = False

                    if agent_task in done:
                        exc = agent_task.exception() if not agent_task.cancelled() else None
                        if exc is None and not agent_task.cancelled():
                            logger.info("Agent task exited cleanly")
                            should_break = True
                        else:
                            logger.error("Agent task crashed: {}", exc)
                            agent_sup.record_failure()
                            if agent_sup.should_escalate():
                                logger.critical(
                                    "Agent task failed {} times consecutively; "
                                    "escalating to full process restart",
                                    agent_sup.consecutive_failures,
                                )
                                reason = f"agent task failed {agent_sup.consecutive_failures} times consecutively"
                                _write_restart_marker(reason)
                                tg = _get_telegram_admin_target(config)
                                if tg:
                                    await _send_telegram_direct(
                                        tg[0], tg[1],
                                        f"⚠️ <b>nanobot 即将重启</b>\n原因: Agent 连续崩溃 {agent_sup.consecutive_failures} 次",
                                    )
                                escalate_to_process_restart = True
                                break
                            delay = agent_sup.backoff_s
                            logger.warning(
                                "Restarting agent task in {:.1f}s (failure #{})",
                                delay,
                                agent_sup.consecutive_failures,
                            )
                            await asyncio.sleep(delay)
                            agent_task = asyncio.create_task(agent.run())
                            agent_sup.mark_started()

                    if channels_task in done:
                        exc = channels_task.exception() if not channels_task.cancelled() else None
                        if exc is None and not channels_task.cancelled():
                            logger.info("Channels task exited cleanly")
                            should_break = True
                        else:
                            logger.error("Channels task crashed: {}", exc)
                            channels_sup.record_failure()
                            if channels_sup.should_escalate():
                                logger.critical(
                                    "Channels task failed {} times consecutively; "
                                    "escalating to full process restart",
                                    channels_sup.consecutive_failures,
                                )
                                reason = f"channels task failed {channels_sup.consecutive_failures} times consecutively"
                                _write_restart_marker(reason)
                                tg = _get_telegram_admin_target(config)
                                if tg:
                                    await _send_telegram_direct(
                                        tg[0], tg[1],
                                        f"⚠️ <b>nanobot 即将重启</b>\n原因: Channels 连续崩溃 {channels_sup.consecutive_failures} 次",
                                    )
                                escalate_to_process_restart = True
                                break
                            delay = channels_sup.backoff_s
                            logger.warning(
                                "Restarting channels task in {:.1f}s (failure #{})",
                                delay,
                                channels_sup.consecutive_failures,
                            )
                            await channels.stop_all()
                            await asyncio.sleep(delay)
                            channels_task = asyncio.create_task(channels.start_all())
                            channels_sup.mark_started()

                    if should_break:
                        break
            except KeyboardInterrupt:
                console.print("\nShutting down...")
            finally:
                if agent_task and not agent_task.done():
                    agent.stop()
                    agent_task.cancel()
                if channels_task and not channels_task.done():
                    channels_task.cancel()
                await asyncio.gather(
                    *(task for task in (agent_task, channels_task) if task),
                    return_exceptions=True,
                )
                await agent.close_mcp()
                heartbeat.stop()
                if repo_sync_watcher:
                    repo_sync_watcher.stop()
                cron.stop()
                agent.stop()
                await channels.stop_all()

        asyncio.run(run())
        if escalate_to_process_restart or restart_requested:
            instance_lock.release()
            os.execv(sys.executable, [sys.executable, "-m", "nanobot", *restart_argv])
    finally:
        instance_lock.release()
