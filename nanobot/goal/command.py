"""User commands for starting and cancelling a sustained goal."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from typing import Any

from nanobot.bus.events import OutboundMessage
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventContext
from nanobot.command.builtin import cmd_stop
from nanobot.command.results import command_reply, line
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

GOAL_COMMAND_SPEC = BuiltinCommandSpec.localized(
    GOAL_COMMAND,
    "activity",
    "<goal>",
    lifecycle="agent_turn_with_args",
    accepts_args=True,
)


async def cmd_goal(ctx: CommandInput) -> CommandExpansion | OutboundMessage:
    """Expand an explicit goal command into model-only input."""
    goal = ctx.args.strip()
    def reply(key: str) -> OutboundMessage:
        return command_reply(ctx.msg, GOAL_COMMAND, line(key))

    if not goal:
        return reply("goal.usage")
    if not ctx.is_user_turn:
        return reply("goal.userOnly")

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
        temporary_session_error=reply("goal.temporary"),
    )


async def cmd_cancel_goal(ctx: CommandContext) -> OutboundMessage:
    """Cancel a user's saved goal, stopping active goal work before committing."""
    def reply(key: str) -> OutboundMessage:
        return command_reply(ctx.msg, "/cancel_goal", line(key))

    if not ctx.is_user_turn:
        return reply("goal.cancelUserOnly")
    session = await ctx.loop.sessions.state.read_header(ctx.key)
    if session is None or not session.policy.persist:
        return reply("goal.none")
    if ctx.msg.session_generation is not None and ctx.msg.session_generation != session.generation:
        return reply("goal.changed")
    goal = parse_goal_state(goal_state_raw(session.metadata))
    if goal is None or goal.get("status") not in {"active", "blocked"}:
        return reply("goal.none")

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
        return reply("goal.changed")
    except (OSError, sqlite3.Error):
        return reply("goal.saveFailed")
    return reply("goal.cancelled" if changed else "goal.none")


def register_goal_command(router: CommandRouter) -> None:
    """Register goal input and user-only cancellation."""
    router.input_command(GOAL_COMMAND, cmd_goal)
    router.add_spec(GOAL_COMMAND_SPEC, after="/model")
    router.priority("/cancel_goal", cmd_cancel_goal)
    router.exact("/cancel_goal", cmd_cancel_goal)
    router.add_spec(BuiltinCommandSpec.localized("/cancel_goal", "circle-x"), after=GOAL_COMMAND)
