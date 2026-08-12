"""Direct and interactive agent CLI command."""

import asyncio
import signal
import sys
from collections.abc import Awaitable, Callable
from types import FrameType
from typing import Any

import typer
from rich.console import Console

from nanobot import __logo__
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.outbound_events import (
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_event_from_message,
)
from nanobot.cli import terminal as cli_terminal
from nanobot.cli.log_control import _set_nanobot_logs
from nanobot.cli.runtime_config import (
    _load_runtime_config,
    _migrate_cron_store,
    _model_display,
    _print_agent_start_error,
)
from nanobot.cli.stream import StreamRenderer, ThinkingSpinner
from nanobot.config.paths import is_default_workspace
from nanobot.utils.helpers import (
    sanitize_surrogates as _sanitize_surrogates,
)
from nanobot.utils.helpers import (
    sync_workspace_templates,
)
from nanobot.utils.restart import (
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)

console = Console()


def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    markdown: bool = typer.Option(
        True,
        "--markdown/--no-markdown",
        help="Render assistant output as Markdown",
    ),
    logs: bool = typer.Option(
        False,
        "--logs/--no-logs",
        help="Show nanobot runtime logs during chat",
    ),
):
    """Interact with the agent directly."""
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.providers.factory import make_provider
    from nanobot.providers.image_generation import image_gen_provider_configs

    runtime_config = _load_runtime_config(config, workspace)
    try:
        provider = make_provider(runtime_config)
    except ValueError as exc:
        _print_agent_start_error(exc)
        raise typer.Exit(1) from exc

    sync_workspace_templates(runtime_config.workspace_path)

    bus = MessageBus()

    # Preserve existing single-workspace installs, but keep custom workspaces clean.
    if is_default_workspace(runtime_config.workspace_path):
        _migrate_cron_store(runtime_config)

    # Create cron service with workspace-scoped store
    cron_store_path = runtime_config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    tools = ToolRegistry()
    mcp_provider = MCPProvider.from_config(runtime_config, tools)

    _set_nanobot_logs(logs)

    try:
        agent_loop = AgentLoop.from_config(
            runtime_config,
            bus,
            provider=provider,
            cron_service=cron,
            image_generation_provider_configs=image_gen_provider_configs(runtime_config),
            hook_factories=[create_file_edit_activity_hook],
            tool_registry=tools,
        )
    except ValueError as exc:
        _print_agent_start_error(exc)
        raise typer.Exit(1) from exc
    restart_notice = consume_restart_notice_from_env()
    if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
        cli_terminal._print_agent_response(
            format_restart_completed_message(restart_notice.started_at_raw),
            render_markdown=False,
        )

    async def _close_runtime() -> None:
        try:
            await agent_loop.aclose()
        finally:
            await mcp_provider.aclose()

    # Shared reference for progress callbacks
    _thinking: ThinkingSpinner | None = None

    def _make_progress(
        renderer: StreamRenderer | None = None,
    ) -> Callable[..., Awaitable[None]]:
        reasoning_buffer = cli_terminal._ReasoningBuffer()

        async def _cli_progress(
            content: str,
            *,
            tool_hint: bool = False,
            reasoning: bool = False,
            **_kwargs: Any,
        ) -> None:
            ch = agent_loop.channels_config

            if _kwargs.get("reasoning_end"):
                if ch and not ch.show_reasoning:
                    reasoning_buffer.clear()
                else:
                    cli_terminal._flush_cli_reasoning(reasoning_buffer, _thinking, renderer)
                return

            if reasoning:
                if ch and not ch.show_reasoning:
                    reasoning_buffer.clear()
                    return
                text = reasoning_buffer.add(content)
                if text:
                    cli_terminal._print_cli_reasoning(text, _thinking, renderer)
                return
            if ch and tool_hint and not ch.send_tool_hints:
                return
            if ch and not tool_hint and not ch.send_progress:
                return
            cli_terminal._print_cli_progress_line(content, _thinking, renderer)

        return _cli_progress

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once() -> None:
            try:
                await mcp_provider.connect()
                renderer = StreamRenderer(
                    render_markdown=markdown,
                    bot_name=runtime_config.agents.defaults.bot_name,
                    bot_icon=runtime_config.agents.defaults.bot_icon,
                )
                response = await agent_loop.process_direct(
                    message,
                    session_id,
                    on_progress=_make_progress(renderer),
                    on_stream=renderer.on_delta,
                    on_stream_end=renderer.on_end,
                )
                if not renderer.streamed:
                    await renderer.close()
                    print_kwargs: dict[str, Any] = {}
                    if renderer.header_printed:
                        print_kwargs["show_header"] = False
                    cli_terminal._print_agent_response(
                        response.content if response else "",
                        render_markdown=markdown,
                        metadata=response.metadata if response else None,
                        **print_kwargs,
                    )
            finally:
                await _close_runtime()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from nanobot.bus.events import InboundMessage

        cli_terminal._init_prompt_session()
        _model, _preset_tag = _model_display(runtime_config)
        _icon = runtime_config.agents.defaults.bot_icon or __logo__
        console.print(
            f"{_icon} Interactive mode [bold blue]({_model})[/bold blue]{_preset_tag} "
            "— type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n"
        )

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _handle_signal(signum: int, _frame: FrameType | None) -> None:
            sig_name = signal.Signals(signum).name
            cli_terminal._restore_terminal()
            console.print(f"\nReceived {sig_name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP is not available on Windows
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive() -> None:
            await mcp_provider.connect()
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[Any] = []
            renderer: StreamRenderer | None = None
            reasoning_buffer = cli_terminal._ReasoningBuffer()

            async def _consume_outbound() -> None:
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        event = outbound_event_from_message(msg)

                        if isinstance(event, StreamDeltaEvent):
                            if renderer:
                                await renderer.on_delta(msg.content)
                            continue
                        if isinstance(event, StreamEndEvent):
                            if renderer:
                                await renderer.on_end(
                                    resuming=event.resuming,
                                )
                            continue
                        if isinstance(event, StreamedResponseEvent):
                            if msg.content and renderer and not renderer.streamed:
                                await renderer.close()
                                print_kwargs: dict[str, Any] = {}
                                if renderer.header_printed:
                                    print_kwargs["show_header"] = False
                                cli_terminal._print_agent_response(
                                    msg.content,
                                    render_markdown=markdown,
                                    metadata=msg.metadata,
                                    **print_kwargs,
                                )
                            turn_done.set()
                            continue

                        if await cli_terminal._maybe_print_interactive_progress(
                            msg,
                            None,
                            agent_loop.channels_config,
                            renderer,
                            reasoning_buffer,
                        ):
                            continue

                        if not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg)
                            turn_done.set()
                        elif msg.content:
                            await cli_terminal._print_interactive_response(
                                msg.content,
                                render_markdown=markdown,
                                metadata=msg.metadata,
                            )

                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        cli_terminal._flush_pending_tty_input()
                        # Stop spinner before user input to avoid prompt_toolkit conflicts
                        if renderer:
                            renderer.stop_for_input()
                        user_input = _sanitize_surrogates(
                            await cli_terminal._read_interactive_input_async()
                        )
                        command = user_input.strip()
                        if not command:
                            continue

                        if cli_terminal._is_exit_command(command):
                            cli_terminal._restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        turn_done.clear()
                        turn_response.clear()
                        reasoning_buffer.clear()
                        renderer = StreamRenderer(
                            render_markdown=markdown,
                            bot_name=runtime_config.agents.defaults.bot_name,
                            bot_icon=runtime_config.agents.defaults.bot_icon,
                        )

                        await bus.publish_inbound(
                            InboundMessage(
                                channel=cli_channel,
                                sender_id="user",
                                chat_id=cli_chat_id,
                                content=user_input,
                                metadata={"_wants_stream": True},
                            )
                        )

                        await turn_done.wait()

                        if turn_response:
                            response_msg = turn_response[0]
                            content = response_msg.content
                            meta = response_msg.metadata
                            if content and not isinstance(
                                response_msg.event,
                                StreamedResponseEvent,
                            ):
                                if renderer:
                                    await renderer.close()
                                print_kwargs: dict[str, Any] = {}
                                if renderer and renderer.header_printed:
                                    print_kwargs["show_header"] = False
                                cli_terminal._print_agent_response(
                                    content,
                                    render_markdown=markdown,
                                    metadata=meta,
                                    **print_kwargs,
                                )
                        elif renderer and not renderer.streamed:
                            await renderer.close()
                    except KeyboardInterrupt:
                        cli_terminal._restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        cli_terminal._restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await _close_runtime()

        asyncio.run(run_interactive())
