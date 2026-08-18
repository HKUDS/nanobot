"""Python runtime for one-shot agent calls and the compatibility prompt."""

import asyncio
import signal
import sys
from types import FrameType
from typing import Any

import typer

from nanobot import __logo__
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import (
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    outbound_event_from_message,
)
from nanobot.bus.queue import MessageBus
from nanobot.cli import terminal as cli_terminal
from nanobot.cli.log_control import _set_nanobot_logs
from nanobot.cli.runtime_config import (
    _migrate_cron_store,
    _model_display,
    _print_agent_start_error,
)
from nanobot.cli.stream import StreamRenderer
from nanobot.config.paths import is_default_workspace
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.providers.factory import make_provider
from nanobot.providers.image_generation import image_gen_provider_configs
from nanobot.utils.helpers import sanitize_surrogates, sync_workspace_templates
from nanobot.utils.restart import (
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)


def run_local_agent(
    config: Config,
    *,
    message: str | None,
    session_id: str,
    markdown: bool,
    logs: bool,
) -> None:
    """Run without the gateway: once for a message, otherwise as the classic prompt."""
    runtime = _LocalAgent(config, logs=logs, session_id=session_id)
    if message is not None:
        asyncio.run(runtime.run_once(message, session_id=session_id, markdown=markdown))
    else:
        runtime.run_classic(session_id=session_id, markdown=markdown)


class _LocalAgent:
    def __init__(self, config: Config, *, logs: bool, session_id: str) -> None:
        self.config = config
        try:
            provider = make_provider(config)
        except ValueError as exc:
            _print_agent_start_error(exc)
            raise typer.Exit(1) from exc

        sync_workspace_templates(config.workspace_path)
        if is_default_workspace(config.workspace_path):
            _migrate_cron_store(config)

        self.bus = MessageBus()
        tools = ToolRegistry()
        self.mcp = MCPProvider.from_config(config, tools)
        _set_nanobot_logs(logs)
        try:
            self.loop = AgentLoop.from_config(
                config,
                self.bus,
                provider=provider,
                cron_service=CronService(config.workspace_path / "cron" / "jobs.json"),
                image_generation_provider_configs=image_gen_provider_configs(config),
                hook_factories=[create_file_edit_activity_hook],
                tool_registry=tools,
            )
        except ValueError as exc:
            _print_agent_start_error(exc)
            raise typer.Exit(1) from exc

        notice = consume_restart_notice_from_env()
        if notice and should_show_cli_restart_notice(notice, session_id):
            cli_terminal._print_agent_response(
                format_restart_completed_message(notice.started_at_raw),
                render_markdown=False,
            )

    async def close(self) -> None:
        try:
            await self.loop.aclose()
        finally:
            await self.mcp.aclose()

    def renderer(self, markdown: bool) -> StreamRenderer:
        return StreamRenderer(
            render_markdown=markdown,
            bot_name=self.config.agents.defaults.bot_name,
            bot_icon=self.config.agents.defaults.bot_icon,
        )

    async def run_once(self, message: str, *, session_id: str, markdown: bool) -> None:
        try:
            await self.mcp.connect()
            renderer = self.renderer(markdown)
            reasoning_buffer = cli_terminal._ReasoningBuffer()

            async def report(
                content: str,
                *,
                tool_hint: bool = False,
                reasoning: bool = False,
                **kwargs: Any,
            ) -> None:
                channel_config = self.loop.channels_config
                if kwargs.get("reasoning_end"):
                    if channel_config and not channel_config.show_reasoning:
                        reasoning_buffer.clear()
                    else:
                        cli_terminal._flush_cli_reasoning(reasoning_buffer, None, renderer)
                    return
                if reasoning:
                    if channel_config and not channel_config.show_reasoning:
                        reasoning_buffer.clear()
                        return
                    text = reasoning_buffer.add(content)
                    if text:
                        cli_terminal._print_cli_reasoning(text, None, renderer)
                    return
                if channel_config and tool_hint and not channel_config.send_tool_hints:
                    return
                if channel_config and not tool_hint and not channel_config.send_progress:
                    return
                cli_terminal._print_cli_progress_line(content, None, renderer)

            response = await self.loop.process_direct(
                message,
                session_id,
                on_progress=report,
                on_stream=renderer.on_delta,
                on_stream_end=renderer.on_end,
            )
            if renderer.streamed:
                return
            await renderer.close()
            cli_terminal._print_agent_response(
                response.content if response else "",
                render_markdown=markdown,
                metadata=response.metadata if response else None,
                **({"show_header": False} if renderer.header_printed else {}),
            )
        finally:
            await self.close()

    def run_classic(self, *, session_id: str, markdown: bool) -> None:
        cli_terminal._init_prompt_session()
        model, preset_tag = _model_display(self.config)
        icon = self.config.agents.defaults.bot_icon or __logo__
        cli_terminal.console.print(
            f"{icon} Interactive mode [bold blue]({model})[/bold blue]{preset_tag} "
            "— type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n"
        )
        channel, chat_id = (
            session_id.split(":", 1) if ":" in session_id else ("cli", session_id)
        )
        self._install_signal_handlers()
        asyncio.run(self._run_classic_loop(channel, chat_id, markdown=markdown))

    @staticmethod
    def _install_signal_handlers() -> None:
        def exit_on_signal(signum: int, _frame: FrameType | None) -> None:
            cli_terminal._restore_terminal()
            cli_terminal.console.print(f"\nReceived {signal.Signals(signum).name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, exit_on_signal)
        signal.signal(signal.SIGTERM, exit_on_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, exit_on_signal)
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    async def _run_classic_loop(self, channel: str, chat_id: str, *, markdown: bool) -> None:
        await self.mcp.connect()
        bus_task = asyncio.create_task(self.loop.run())
        turn_done = asyncio.Event()
        turn_done.set()
        turn_response: list[OutboundMessage] = []
        renderer: StreamRenderer | None = None
        reasoning_buffer = cli_terminal._ReasoningBuffer()

        async def consume_outbound() -> None:
            while True:
                try:
                    msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
                    event = outbound_event_from_message(msg)
                    if isinstance(event, StreamDeltaEvent):
                        if renderer:
                            await renderer.on_delta(msg.content)
                        continue
                    if isinstance(event, StreamEndEvent):
                        if renderer:
                            await renderer.on_end(resuming=event.resuming)
                        continue
                    if isinstance(event, StreamedResponseEvent):
                        if msg.content and renderer and not renderer.streamed:
                            await renderer.close()
                            cli_terminal._print_agent_response(
                                msg.content,
                                render_markdown=markdown,
                                metadata=msg.metadata,
                                **({"show_header": False} if renderer.header_printed else {}),
                            )
                        turn_done.set()
                        continue
                    if await cli_terminal._maybe_print_interactive_progress(
                        msg,
                        None,
                        self.loop.channels_config,
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

        outbound_task = asyncio.create_task(consume_outbound())
        try:
            while True:
                try:
                    cli_terminal._flush_pending_tty_input()
                    if renderer:
                        renderer.stop_for_input()
                    user_input = sanitize_surrogates(
                        await cli_terminal._read_interactive_input_async()
                    )
                    command = user_input.strip()
                    if not command:
                        continue
                    if cli_terminal._is_exit_command(command):
                        cli_terminal._restore_terminal()
                        cli_terminal.console.print("\nGoodbye!")
                        break

                    turn_done.clear()
                    turn_response.clear()
                    reasoning_buffer.clear()
                    renderer = self.renderer(markdown)
                    await self.bus.publish_inbound(
                        InboundMessage(
                            channel=channel,
                            sender_id="user",
                            chat_id=chat_id,
                            content=user_input,
                            metadata={"_wants_stream": True},
                        )
                    )
                    await turn_done.wait()
                    if turn_response:
                        response = turn_response[0]
                        if response.content and not isinstance(
                            response.event, StreamedResponseEvent
                        ):
                            if renderer:
                                await renderer.close()
                            cli_terminal._print_agent_response(
                                response.content,
                                render_markdown=markdown,
                                metadata=response.metadata,
                                **(
                                    {"show_header": False}
                                    if renderer and renderer.header_printed
                                    else {}
                                ),
                            )
                    elif renderer and not renderer.streamed:
                        await renderer.close()
                except (KeyboardInterrupt, EOFError):
                    cli_terminal._restore_terminal()
                    cli_terminal.console.print("\nGoodbye!")
                    break
        finally:
            self.loop.stop()
            outbound_task.cancel()
            await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
            await self.close()
