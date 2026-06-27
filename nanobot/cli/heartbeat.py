"""Shared heartbeat trigger helpers for gateway ticks and CLI debugging."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.schema import Config
from nanobot.utils.evaluator import evaluate_response

HEARTBEAT_PREAMBLE = (
    "[Your response will be delivered directly to the user's messaging app. "
    "Output ONLY the final user-facing message. Never reference internal "
    "files (HEARTBEAT.md, AWARENESS.md, etc.), your instructions, or your "
    "decision process. If nothing needs reporting, respond with just "
    "'All clear.' and nothing else.]\n\n"
)

_HEARTBEAT_DECISION_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "decide_heartbeat",
            "description": (
                "Decide whether HEARTBEAT.md contains active tasks that should "
                "run now, and summarize those tasks for the execution phase."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "should_run": {
                        "type": "boolean",
                        "description": "true when there are actionable active tasks to execute",
                    },
                    "tasks": {
                        "type": "string",
                        "description": (
                            "Concise actionable summary of the active tasks. "
                            "Leave empty when should_run is false."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short reason for the decision.",
                    },
                },
                "required": ["should_run", "tasks"],
            },
        },
    }
]


@dataclass(frozen=True)
class HeartbeatDecision:
    static_has_active_tasks: bool
    should_run: bool
    tasks: str = ""
    reason: str = ""
    source: str = "static"
    raw_response: str = ""


@dataclass(frozen=True)
class HeartbeatTriggerResult:
    status: str
    dry_run: bool
    decision: HeartbeatDecision
    channel: str = "cli"
    chat_id: str = "direct"
    response: str = ""
    should_notify: bool | None = None
    delivered: bool = False


def heartbeat_has_active_tasks(content: str) -> bool:
    """True if HEARTBEAT.md has task lines, ignoring headers, blanks and comments."""
    in_comment = False
    in_active_section: bool = False
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
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped[4:]:
                in_comment = True
            continue
        if in_active_section is False:
            continue
        return True
    return False


def _heartbeat_lock_path(config: Config) -> Path:
    return config.workspace_path / ".heartbeat-trigger.lock"


def _build_heartbeat_decision_messages(content: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the Phase 1 heartbeat checker for nanobot. Inspect the "
                "provided HEARTBEAT.md content only. Decide whether the Active "
                "Tasks section contains actionable work that should run now. "
                "Ignore comments, templates, examples, and inactive sections. "
                "Do not execute any task. Call decide_heartbeat exactly once."
            ),
        },
        {
            "role": "user",
            "content": f"HEARTBEAT.md:\n\n{content}",
        },
    ]


def _coerce_heartbeat_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "run"}:
            return True
        if lowered in {"false", "no", "n", "0", "skip"}:
            return False
    return default


def _heartbeat_tasks_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(f"- {part}" for part in parts)
    return ""


def _parse_heartbeat_decision_args(response: Any) -> dict[str, Any] | None:
    tool_calls = getattr(response, "tool_calls", None) or []
    if getattr(response, "should_execute_tools", False) and tool_calls:
        args = tool_calls[0].arguments
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed

    content = (getattr(response, "content", None) or "").strip()
    if not content:
        return None
    if content.startswith("```"):
        content = content.strip("`")
        if "\n" in content:
            content = content.split("\n", 1)[1]
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _decide_heartbeat(
    content: str,
    provider: Any,
    model: str,
    *,
    default_run: bool = True,
) -> HeartbeatDecision:
    static_has_active_tasks = heartbeat_has_active_tasks(content)
    if not static_has_active_tasks:
        return HeartbeatDecision(
            static_has_active_tasks=False,
            should_run=False,
            reason="HEARTBEAT.md has no active tasks after the static pre-check.",
        )

    try:
        response = await provider.chat_with_retry(
            messages=_build_heartbeat_decision_messages(content),
            tools=_HEARTBEAT_DECISION_TOOL,
            model=model,
            max_tokens=512,
            temperature=0.0,
        )
    except Exception as exc:
        logger.warning("Heartbeat: Phase 1 decision failed, defaulting to run: {}", exc)
        return HeartbeatDecision(
            static_has_active_tasks=True,
            should_run=default_run,
            reason=f"Phase 1 decision failed; defaulted to {'run' if default_run else 'skip'}.",
            source="fallback",
        )

    args = _parse_heartbeat_decision_args(response)
    if args is None:
        logger.warning("Heartbeat: Phase 1 decision was not structured, defaulting to run")
        return HeartbeatDecision(
            static_has_active_tasks=True,
            should_run=default_run,
            reason=f"Phase 1 decision was not structured; defaulted to {'run' if default_run else 'skip'}.",
            source="fallback",
            raw_response=getattr(response, "content", None) or "",
        )

    should_run = _coerce_heartbeat_bool(args.get("should_run"), default_run)
    tasks = _heartbeat_tasks_text(args.get("tasks"))
    reason = str(args.get("reason") or "").strip()
    return HeartbeatDecision(
        static_has_active_tasks=True,
        should_run=should_run,
        tasks=tasks,
        reason=reason,
        source="llm",
        raw_response=getattr(response, "content", None) or "",
    )


def _build_heartbeat_execution_prompt(content: str, decision: HeartbeatDecision) -> str:
    tasks = decision.tasks.strip() or "The active tasks listed in HEARTBEAT.md."
    return (
        HEARTBEAT_PREAMBLE
        + "Execute the active heartbeat tasks for the user.\n\n"
        + f"Phase 1 extracted tasks:\n{tasks}\n\n"
        + f"Full HEARTBEAT.md for context:\n\n{content}"
    )


def heartbeat_result_payload(result: HeartbeatTriggerResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "dry_run": result.dry_run,
        "target": {"channel": result.channel, "chat_id": result.chat_id},
        "static_has_active_tasks": result.decision.static_has_active_tasks,
        "decision": {
            "should_run": result.decision.should_run,
            "tasks": result.decision.tasks,
            "reason": result.decision.reason,
            "source": result.decision.source,
        },
        "response": result.response,
        "should_notify": result.should_notify,
        "delivered": result.delivered,
    }


async def run_heartbeat_trigger(
    config: Config,
    agent: Any,
    *,
    dry_run: bool = False,
    target: tuple[str, str] | None = None,
    target_picker: Callable[[], tuple[str, str]] | None = None,
    deliver_to_channel: Callable[..., Any] | None = None,
    message_tool: Any = None,
    allow_cli_target: bool = False,
    acquire_lock: bool = True,
) -> HeartbeatTriggerResult:
    """Run the shared heartbeat trigger path used by cron and the debug CLI."""
    from nanobot.bus.events import OutboundMessage

    lock = None
    if acquire_lock:
        from filelock import FileLock, Timeout

        lock_path = _heartbeat_lock_path(config)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(lock_path))
        try:
            lock.acquire(timeout=0)
        except Timeout:
            decision = HeartbeatDecision(
                static_has_active_tasks=False,
                should_run=False,
                reason="Another heartbeat trigger is already running.",
                source="lock",
            )
            logger.info("Heartbeat: trigger skipped because another run is active")
            return HeartbeatTriggerResult(status="busy", dry_run=dry_run, decision=decision)

    try:
        heartbeat_file = config.workspace_path / "HEARTBEAT.md"
        try:
            content = heartbeat_file.read_text(encoding="utf-8")
        except OSError:
            decision = HeartbeatDecision(
                static_has_active_tasks=False,
                should_run=False,
                reason="HEARTBEAT.md is missing.",
            )
            logger.debug("Heartbeat: HEARTBEAT.md missing")
            return HeartbeatTriggerResult(status="missing", dry_run=dry_run, decision=decision)

        decision = await _decide_heartbeat(
            content,
            agent.provider,
            agent.model,
            default_run=True,
        )
        if not decision.static_has_active_tasks:
            logger.debug("Heartbeat: HEARTBEAT.md has no active tasks")
            return HeartbeatTriggerResult(status="skipped", dry_run=dry_run, decision=decision)
        if not decision.should_run:
            logger.info("Heartbeat: Phase 1 decision skipped execution")
            return HeartbeatTriggerResult(status="skipped", dry_run=dry_run, decision=decision)

        channel, chat_id = target or (target_picker() if target_picker else ("cli", "direct"))
        if channel == "cli" and not allow_cli_target:
            logger.debug("Heartbeat: no routable channel target")
            return HeartbeatTriggerResult(
                status="no_target",
                dry_run=dry_run,
                decision=decision,
                channel=channel,
                chat_id=chat_id,
            )

        if dry_run:
            logger.info("Heartbeat: dry-run completed after Phase 1")
            return HeartbeatTriggerResult(
                status="dry_run",
                dry_run=True,
                decision=decision,
                channel=channel,
                chat_id=chat_id,
            )

        async def _silent(*_args, **_kwargs):
            pass

        prompt = _build_heartbeat_execution_prompt(content, decision)
        suppress_token = None
        if message_tool is not None and hasattr(message_tool, "set_suppress_delivery"):
            suppress_token = message_tool.set_suppress_delivery(True)
        try:
            resp = await agent.process_direct(
                prompt,
                session_key="heartbeat",
                channel=channel,
                chat_id=chat_id,
                on_progress=_silent,
            )
        finally:
            if (
                message_tool is not None
                and suppress_token is not None
                and hasattr(message_tool, "reset_suppress_delivery")
            ):
                message_tool.reset_suppress_delivery(suppress_token)
        response = resp.content if resp else ""

        sessions = getattr(agent, "sessions", None)
        if (
            sessions is not None
            and hasattr(sessions, "get_or_create")
            and hasattr(sessions, "save")
        ):
            session = sessions.get_or_create("heartbeat")
            if hasattr(session, "retain_recent_legal_suffix"):
                session.retain_recent_legal_suffix(config.gateway.heartbeat.keep_recent_messages)
            sessions.save(session)

        if not response:
            return HeartbeatTriggerResult(
                status="empty",
                dry_run=False,
                decision=decision,
                channel=channel,
                chat_id=chat_id,
            )

        should_notify = await evaluate_response(
            response,
            prompt,
            agent.provider,
            agent.model,
            default_notify=False,
        )
        if should_notify and deliver_to_channel is not None:
            logger.info("Heartbeat: completed, delivering response")
            await deliver_to_channel(
                OutboundMessage(channel=channel, chat_id=chat_id, content=response),
                record=True,
            )
            return HeartbeatTriggerResult(
                status="delivered",
                dry_run=False,
                decision=decision,
                channel=channel,
                chat_id=chat_id,
                response=response,
                should_notify=True,
                delivered=True,
            )

        if should_notify:
            logger.info("Heartbeat: completed, no delivery callback configured")
            status = "completed"
        else:
            logger.info("Heartbeat: silenced by post-run evaluation")
            status = "silenced"
        return HeartbeatTriggerResult(
            status=status,
            dry_run=False,
            decision=decision,
            channel=channel,
            chat_id=chat_id,
            response=response,
            should_notify=should_notify,
            delivered=False,
        )
    finally:
        if lock is not None:
            lock.release()
