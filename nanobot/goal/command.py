"""Command adapter for explicitly starting a sustained goal."""

from __future__ import annotations

from dataclasses import replace

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandExpansion, CommandInput, CommandRouter
from nanobot.command.spec import BuiltinCommandSpec
from nanobot.session.goal_state import GOAL_COMMAND
from nanobot.session.history_visibility import HIDDEN_HISTORY_META

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


def register_goal_command(router: CommandRouter) -> None:
    """Register the exact usage and task-bearing forms of /goal."""
    router.input_command(GOAL_COMMAND, cmd_goal)
    router.add_spec(GOAL_COMMAND_SPEC, after="/history")
