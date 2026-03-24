"""Agent CLI command and TTY helpers.

Extracted from ``commands.py`` — plain functions registered by the Typer app
in the main command module.
"""

from __future__ import annotations

import asyncio
import os
import select
import signal
import sys
import threading
from pathlib import Path
from typing import Any

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from nanobot import __logo__
from nanobot.cli._shared import (
    _configure_log_sink,
    _make_agent_config,
    _make_provider,
    _print_agent_response,
    console,
)
from nanobot.cli.progress import CliProgressHandler

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:  # crash-barrier: stdin may not be a tty
        return

    try:
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except (OSError, ImportError, AttributeError):
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except OSError:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except (OSError, ImportError, AttributeError):
        pass  # terminal restore is best-effort; ignore if unavailable


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except (OSError, ImportError, AttributeError):
        pass  # terminal state save is best-effort; ignore if unavailable

    history_file = Path.home() / ".nanobot" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _drain_pending_tasks(timeout: float = 0.25) -> None:
    """Give pending background tasks a brief chance to finish before loop shutdown."""
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
    if not pending:
        return
    try:
        await asyncio.wait(pending, timeout=timeout)
    except Exception:  # crash-barrier: must not break shutdown
        return


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return str(
                await _PROMPT_SESSION.prompt_async(
                    HTML("<b fg='ansiblue'>You:</b> "),
                )
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Render assistant output as Markdown"
    ),
    logs: bool = typer.Option(
        False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"
    ),
    timeout_s: int = typer.Option(
        180,
        "--timeout",
        help="Timeout in seconds for single-message mode (--message). Use 0 to disable.",
    ),
) -> None:
    """Interact with the agent directly."""
    from loguru import logger

    from nanobot.agent.agent_factory import build_agent
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService

    config = load_config()

    # Initialize langfuse observability (auto-instruments litellm via OTEL)
    from nanobot.observability.langfuse import init_langfuse
    from nanobot.observability.langfuse import shutdown as shutdown_langfuse

    init_langfuse(config.langfuse)

    bus = MessageBus()
    provider = _make_provider(config)

    # Create cron service for tool usage (no callback needed for CLI unless running)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    # Apply structured logging config from config.log
    _configure_log_sink(config, logger)

    agent_loop = build_agent(
        bus=bus,
        provider=provider,
        config=_make_agent_config(config),
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        routing_config=config.agents.routing,
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx() -> Any:
        if logs:
            from contextlib import nullcontext

            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]nanobot is thinking...[/dim]", spinner="dots")

    handler = CliProgressHandler(console=console, channels_config=agent_loop.channels_config)

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once() -> None:
            try:
                with _thinking_ctx():
                    coro = agent_loop.process_direct(message, session_id, on_progress=handler)
                    if timeout_s > 0:
                        response = await asyncio.wait_for(coro, timeout=float(timeout_s))
                    else:
                        response = await coro
                _print_agent_response(response, render_markdown=markdown)
            except TimeoutError:
                console.print(
                    f"[red]Error:[/red] agent timed out after {timeout_s}s in single-message mode."
                )
                raise typer.Exit(124) from None
            finally:
                agent_loop.stop()
                try:
                    await asyncio.wait_for(agent_loop.close_mcp(), timeout=5.0)
                except TimeoutError:
                    console.print(
                        "[yellow]Warning:[/yellow] timed out while closing provider/MCP resources."
                    )
                try:
                    await asyncio.wait_for(_drain_pending_tasks(), timeout=2.0)
                except TimeoutError:
                    pass  # drain is best-effort; proceed with shutdown
                shutdown_langfuse()

        watchdog: threading.Timer | None = None
        if timeout_s > 0:

            def _hard_timeout_kill() -> None:
                # Last-resort guard for blocking calls that ignore cancellation.
                os.write(2, f"\nError: agent exceeded hard timeout ({timeout_s}s)\n".encode())
                os._exit(124)

            watchdog = threading.Timer(float(timeout_s), _hard_timeout_kill)
            watchdog.daemon = True
            watchdog.start()

        try:
            asyncio.run(run_once())
        finally:
            if watchdog:
                watchdog.cancel()
    else:
        # Interactive mode — route through bus like other channels
        from nanobot.bus.events import InboundMessage

        _init_prompt_session()
        console.print(
            f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n"
        )

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _exit_on_sigint(signum: int, frame: object) -> None:
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

        async def run_interactive() -> None:
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound() -> None:
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown)
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        turn_done.clear()
                        turn_response.clear()

                        await bus.publish_inbound(
                            InboundMessage(
                                channel=cli_channel,
                                sender_id="user",
                                chat_id=cli_chat_id,
                                content=user_input,
                            )
                        )

                        with _thinking_ctx():
                            await turn_done.wait()

                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()
                await _drain_pending_tasks()
                shutdown_langfuse()

        asyncio.run(run_interactive())
