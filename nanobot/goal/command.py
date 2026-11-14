"""User commands for starting and cancelling a sustained goal."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from typing import Any

from nanobot.bus.events import OutboundMessage
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventContext
from nanobot.command.builtin import cmd_stop
from nanobot.command.router import CommandContext, CommandExpansion, CommandInput, CommandRouter
from nanobot.command.spec import BuiltinCommandSpec
from nanobot.session.goal_state import (
    GOAL_COMMAND,
    GOAL_STATE_KEY,
    discard_legacy_goal_state_key,
    goal_state_raw,
    parse_goal_state,
)
from nanobot.session.history_visibility import HIDDEN_HISTORY_META
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.utils.cancellation import shield_and_drain

GOAL_COMMAND_SPEC = BuiltinCommandSpec(
    GOAL_COMMAND,
    "Start long-running goal",
    "Tell the agent to treat the request as a long-running goal.",
    "activity",
    "<goal>",
    lifecycle="agent_turn_with_args",
    accepts_args=True,
)


async def cmd_goal(ctx: CommandInput) -> CommandExpansion | OutboundMessage:
    """Expand an explicit goal command into model-only input."""
    goal = ctx.args.strip()
    if not goal:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /goal <long-running task description>",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    if not ctx.is_user_turn:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Goal mode can only be started by a user `/goal <task>` command.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    return CommandExpansion(
        message=replace(
            ctx.msg,
            content=goal,
            metadata={
                **ctx.msg.metadata,
                "original_command": GOAL_COMMAND,
                "original_content": ctx.msg.content,
                "goal_requested": True,
                HIDDEN_HISTORY_META: {"kind": "goal_request"},
            },
        ),
        temporary_session_error="Goals can't start in a temporary session. Use a persistent session for `/goal`.",
    )


async def cmd_cancel_goal(ctx: CommandContext) -> OutboundMessage:
    """Cancel a user's saved goal, stopping active goal work before committing."""
    def reply(content: str) -> OutboundMessage:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content,
            metadata={**ctx.msg.metadata, "render_as": "text"},
        )

    if not ctx.is_user_turn:
        return reply("Goals can only be cancelled by a user `/cancel_goal` command.")
    session = await ctx.loop.sessions.state.read_header(ctx.key)
    if session is None or not session.policy.persist:
        return reply("No goal to cancel.")
    if ctx.msg.session_generation is not None and ctx.msg.session_generation != session.generation:
        return reply("The session changed. Try /cancel_goal again.")
    goal = parse_goal_state(goal_state_raw(session.metadata))
    if goal is None or goal.get("status") not in {"active", "blocked"}:
        return reply("No goal to cancel.")

    if goal.get("status") == "active":
        await cmd_stop(ctx)

    async def cancel_and_publish() -> bool:
        def cancel(metadata: dict[str, Any]) -> bool:
            current = parse_goal_state(goal_state_raw(metadata))
            if current is None or current.get("status") not in {"active", "blocked"}:
                return False
            metadata[GOAL_STATE_KEY] = {
                **current, "status": "cancelled", "ended_at": datetime.now().isoformat(),
                "recap": "Cancelled by user.",
            }
            discard_legacy_goal_state_key(metadata)
            return True

        changed, metadata = await ctx.loop.sessions.state.mutate_metadata(
            ctx.key, cancel, expected_generation=session.generation,
        )
        await ctx.loop.bus.publish(GoalStateChanged(
            context=RuntimeEventContext(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                session_key=ctx.key, metadata=dict(ctx.msg.metadata),
            ),
            session_metadata=metadata,
        ))
        return changed

    try:
        changed = await shield_and_drain(cancel_and_publish())
    except SessionConflictError:
        return reply("The session changed. Try /cancel_goal again.")
    except (OSError, sqlite3.Error):
        return reply("Could not save the goal cancellation. Try /cancel_goal again.")
    return reply("Goal cancelled." if changed else "No goal to cancel.")


def register_goal_command(router: CommandRouter) -> None:
    """Register goal input and user-only cancellation."""
    router.input_command(GOAL_COMMAND, cmd_goal)
    router.add_spec(GOAL_COMMAND_SPEC, after="/model")
    router.priority("/cancel_goal", cmd_cancel_goal)
    router.exact("/cancel_goal", cmd_cancel_goal)
    router.add_spec(BuiltinCommandSpec(
        "/cancel_goal", "Cancel goal", "Cancel the saved goal and stop active goal work.", "circle-x",
    ), after=GOAL_COMMAND)
