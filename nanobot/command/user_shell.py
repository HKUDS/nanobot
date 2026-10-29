"""Trusted user Shell commands, outside model-turn execution policy."""

from contextlib import ExitStack

from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from nanobot.agent.tools.shell import ExecTool
from nanobot.bus.events import INBOUND_META_USER_SHELL, OutboundMessage
from nanobot.command.router import CommandContext
from nanobot.security.workspace_access import bind_workspace_scope, reset_workspace_scope


async def cmd_user_shell(ctx: CommandContext) -> OutboundMessage:
    """Run a trusted local command to completion under its admitted policy."""
    metadata = dict(ctx.msg.metadata or {})
    command = ctx.args.strip()
    if (
        ctx.msg.channel != "websocket"
        or metadata.get("webui") is not True
        or metadata.get(INBOUND_META_USER_SHELL) is not True
    ):
        content = "Shell commands are only available from a trusted local client."
    elif not command:
        content = "Type a command after `!`, for example `!pwd`."
    elif not isinstance(tool := ctx.loop.tools.get("exec"), ExecTool):
        content = "Shell execution is disabled in this nanobot configuration."
    else:
        session = ctx.session or await ctx.loop.sessions.state.get(ctx.key)
        scope = ctx.loop.workspace_scopes.for_turn(
            channel=ctx.msg.channel,
            message_metadata=metadata,
            session_metadata=session.metadata,
        )
        request_token = bind_request_context(RequestContext(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            message_id=metadata.get("message_id"),
            session_key=ctx.key,
            session_generation=session.generation,
            original_user_text=f"!{command}",
            runtime=ctx.runtime,
            metadata=metadata,
            sender_id=ctx.msg.sender_id,
            turn_id=metadata.get("webui_turn_id"),
            workspace=scope.project_path,
            log_content=session.policy.log_content,
        ))
        workspace_token = bind_workspace_scope(scope)
        try:
            with ExitStack() as stack:
                for turn_scope in ctx.turn_scopes:
                    stack.enter_context(turn_scope)
                # A trusted user command owns the complete result. The model's
                # bounded observation/exec_session behavior remains in its tool.
                content = str(await tool.execute_to_completion(
                    command=command, working_dir=str(scope.project_path),
                ))
        finally:
            reset_workspace_scope(workspace_token)
            reset_request_context(request_token)
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content,
        metadata={**metadata, "render_as": "text"},
    )
