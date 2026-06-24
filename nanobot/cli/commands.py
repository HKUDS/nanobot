"""CLI commands for nanobot."""

import asyncio
import datetime as _datetime
import os
import pathlib as _pathlib
import select
import signal
import sys
from collections.abc import Callable, Iterable
from contextlib import nullcontext, suppress
from pathlib import Path
from typing import Any

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        with suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Keep console encoding setup before importing CLI UI/logging libraries.
import typer  # noqa: E402
from loguru import logger  # noqa: E402

# Remove default handler and re-add with unified nanobot format
logger.remove()
_log_handler_id = logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <5}</level> | "
        "<cyan>{extra[channel]}</cyan> | "
        "<level>{message}</level>"
    ),
    level="INFO",
    colorize=None,
    filter=lambda record: record["extra"].setdefault("channel", "-") or True,
)

from prompt_toolkit import PromptSession, print_formatted_text  # noqa: E402
from prompt_toolkit.application import run_in_terminal  # noqa: E402
from prompt_toolkit.formatted_text import ANSI, HTML  # noqa: E402
from prompt_toolkit.history import FileHistory  # noqa: E402
from prompt_toolkit.patch_stdout import patch_stdout  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from nanobot import __logo__, __version__  # noqa: E402
from nanobot.agent.loop import AgentLoop  # noqa: E402
from nanobot.cli.gateway import create_gateway_app  # noqa: E402
from nanobot.cli.stream import StreamRenderer, ThinkingSpinner  # noqa: E402
from nanobot.config.paths import get_workspace_path, is_default_workspace  # noqa: E402
from nanobot.config.schema import Config  # noqa: E402
from nanobot.utils.evaluator import evaluate_response  # noqa: E402
from nanobot.utils.helpers import sync_workspace_templates  # noqa: E402
from nanobot.utils.restart import (  # noqa: E402
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)
from nanobot.webui.sidebar_state import read_webui_sidebar_state  # noqa: E402


def _sanitize_surrogates(text: str) -> str:
    """Reconstruct surrogate pairs into real characters; replace lone surrogates.

    On Windows, console input may produce lone surrogate code points (e.g.
    ``\\ud83d\\udc08`` for U+1F408).  Round-tripping through UTF-16 reconstructs
    paired surrogates into their actual characters and replaces unpaired ones
    with U+FFFD.
    """
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")


def _signal_name(signum: int) -> str:
    with suppress(ValueError):
        return signal.Signals(signum).name
    return f"signal {signum}"


def _ensure_gateway_tty_signal_mode() -> None:
    """Keep foreground gateway Ctrl+C usable even after a raw-mode TTY leak."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    with suppress(Exception):
        import termios

        attrs = termios.tcgetattr(fd)
        lflag = attrs[3]
        required = termios.ISIG | termios.ICANON | termios.ECHO
        if (lflag & required) == required:
            return
        attrs[3] = lflag | required
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
        logger.debug("Restored foreground gateway TTY signal mode")


def _install_gateway_shutdown_handlers(
    loop: asyncio.AbstractEventLoop,
    shutdown_event: asyncio.Event,
    tasks: list[asyncio.Task],
    print_status: Callable[[str], None],
) -> Callable[[], None]:
    """Install foreground gateway signal handlers and return a restore callback."""
    loop_signals: list[int] = []
    previous_handlers: list[tuple[int, Any]] = []
    shutdown_requested = False

    def request_shutdown(signum: int) -> None:
        nonlocal shutdown_requested
        sig_name = _signal_name(signum)
        if shutdown_requested:
            logger.warning("Forcing gateway shutdown after repeated {}", sig_name)
            for task in tasks:
                if not task.done():
                    task.cancel()
            return
        shutdown_requested = True
        logger.info("Gateway shutdown requested by {}", sig_name)
        print_status("\nShutting down... Press Ctrl+C again to force.")
        shutdown_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_shutdown, signum)
        except (NotImplementedError, RuntimeError, ValueError):
            try:
                previous = signal.getsignal(signum)
                signal.signal(signum, lambda sig, _frame: request_shutdown(sig))
            except (RuntimeError, ValueError):
                logger.debug("Could not install gateway handler for {}", _signal_name(signum))
                continue
            previous_handlers.append((signum, previous))
        else:
            loop_signals.append(signum)

    def restore() -> None:
        for signum in loop_signals:
            with suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(signum)
        for signum, handler in previous_handlers:
            with suppress(RuntimeError, ValueError):
                signal.signal(signum, handler)

    return restore


class SafeFileHistory(FileHistory):
    """FileHistory subclass that sanitizes surrogate characters on write.

    On Windows, special Unicode input (emoji, mixed-script) can produce
    surrogate characters that crash prompt_toolkit's file write.
    See issue #2846.
    """

    def store_string(self, string: str) -> None:
        super().store_string(_sanitize_surrogates(string))


app = typer.Typer(
    name="nanobot",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
_REASONING_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
_REASONING_FLUSH_CHARS = 60

_HEARTBEAT_PREAMBLE = (
    "[Your response will be delivered directly to the user's messaging app. "
    "Output ONLY the final user-facing message. Never reference internal "
    "files (HEARTBEAT.md, AWARENESS.md, etc.), your instructions, or your "
    "decision process. If nothing needs reporting, respond with just "
    "'All clear.' and nothing else.]\n\n"
)


def _heartbeat_has_active_tasks(content: str) -> bool:
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


def _pick_heartbeat_target_from_sessions(
    *,
    enabled_channels: Iterable[str],
    sessions: Iterable[dict[str, Any]],
    archived_keys: Iterable[str],
) -> tuple[str, str]:
    enabled = set(enabled_channels)
    archived = set(archived_keys)
    for item in sessions:
        key = item.get("key") or ""
        if key in archived:
            continue
        if ":" not in key:
            continue
        channel, chat_id = key.split(":", 1)
        if channel in {"cli", "system"}:
            continue
        if channel in enabled and chat_id:
            return channel, chat_id
    return "cli", "direct"


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
    except Exception:
        return

    with suppress(Exception):
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return

    with suppress(Exception):
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    with suppress(Exception):
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    with suppress(Exception):
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())

    from nanobot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=SafeFileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


def _make_console() -> Console:
    return Console(file=sys.stdout)


def _render_interactive_ansi(render_fn) -> str:
    """Render Rich output to ANSI so prompt_toolkit can print it safely."""
    ansi_console = Console(
        force_terminal=sys.stdout.isatty(),
        color_system=console.color_system or "standard",
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()


def _print_agent_response(
    response: str,
    render_markdown: bool,
    metadata: dict | None = None,
    show_header: bool = True,
) -> None:
    """Render assistant response with consistent terminal styling."""
    console = _make_console()
    content = response or ""
    body = _response_renderable(content, render_markdown, metadata)
    if show_header:
        console.print()
        console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


def _response_renderable(content: str, render_markdown: bool, metadata: dict | None = None):
    """Render plain-text command output without markdown collapsing newlines."""
    if not render_markdown:
        return Text(content)
    if (metadata or {}).get("render_as") == "text":
        return Text(content)
    return Markdown(content)


async def _print_interactive_line(text: str) -> None:
    """Print async interactive updates with prompt_toolkit-safe Rich styling."""
    def _write() -> None:
        ansi = _render_interactive_ansi(
            lambda c: c.print(f"  [dim]↳ {text}[/dim]")
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def _print_interactive_response(
    response: str,
    render_markdown: bool,
    metadata: dict | None = None,
) -> None:
    """Print async interactive replies with prompt_toolkit-safe Rich styling."""
    def _write() -> None:
        content = response or ""
        ansi = _render_interactive_ansi(
            lambda c: (
                c.print(),
                c.print(f"[cyan]{__logo__} nanobot[/cyan]"),
                c.print(_response_renderable(content, render_markdown, metadata)),
                c.print(),
            )
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


def _print_cli_progress_line(text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None) -> None:
    """Print a CLI progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"  [dim]↳ {text}[/dim]")


class _ReasoningBuffer:
    def __init__(self) -> None:
        self._text = ""

    def add(self, text: str) -> str | None:
        if not text:
            return None
        self._text += text
        if self._should_flush(text):
            return self.flush()
        return None

    def flush(self) -> str | None:
        text = self._text.strip()
        self._text = ""
        return text or None

    def clear(self) -> None:
        self._text = ""

    def _should_flush(self, text: str) -> bool:
        stripped = text.rstrip()
        return (
            "\n" in text
            or stripped.endswith(_REASONING_SENTENCE_ENDINGS)
            or len(self._text) >= _REASONING_FLUSH_CHARS
        )


def _print_cli_reasoning(text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None) -> None:
    """Print reasoning/thinking content in a distinct style."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"[dim italic]✻ {text}[/dim italic]")


def _flush_cli_reasoning(
    reasoning_buffer: _ReasoningBuffer,
    thinking: ThinkingSpinner | None,
    renderer: StreamRenderer | None = None,
) -> None:
    text = reasoning_buffer.flush()
    if text:
        _print_cli_reasoning(text, thinking, renderer)


async def _print_interactive_progress_line(text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None) -> None:
    """Print an interactive progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    if renderer:
        with renderer.pause_spinner():
            renderer.ensure_header()
            renderer.console.print(f"  [dim]↳ {text}[/dim]")
    else:
        with thinking.pause() if thinking else nullcontext():
            await _print_interactive_line(text)


async def _maybe_print_interactive_progress(
    msg: Any,
    thinking: ThinkingSpinner | None,
    channels_config: Any,
    renderer: StreamRenderer | None = None,
    reasoning_buffer: _ReasoningBuffer | None = None,
) -> bool:
    metadata = msg.metadata or {}
    if metadata.get("_retry_wait"):
        await _print_interactive_progress_line(msg.content, thinking, renderer)
        return True

    if not metadata.get("_progress"):
        return False

    reasoning_buffer = reasoning_buffer or _ReasoningBuffer()

    if metadata.get("_reasoning_end"):
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
        else:
            _flush_cli_reasoning(reasoning_buffer, thinking, renderer)
        return True

    is_tool_hint = metadata.get("_tool_hint", False)
    is_reasoning = metadata.get("_reasoning", False) or metadata.get("_reasoning_delta", False)
    if is_reasoning:
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
            return True
        text = reasoning_buffer.add(msg.content)
        if text:
            _print_cli_reasoning(text, thinking, renderer)
        return True
    if channels_config and is_tool_hint and not channels_config.send_tool_hints:
        return True
    if channels_config and not is_tool_hint and not channels_config.send_progress:
        return True

    await _print_interactive_progress_line(msg.content, thinking, renderer)
    return True


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


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
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    wizard: bool = typer.Option(False, "--wizard", help="Use interactive wizard"),
):
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, load_config, save_config, set_config_path
    from nanobot.config.schema import Config

    if config:
        config_path = Path(config).expanduser().resolve()
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")
    else:
        config_path = get_config_path()

    def _apply_workspace_override(loaded: Config) -> Config:
        if workspace:
            loaded.agents.defaults.workspace = workspace
        return loaded

    # Create or update config
    if config_path.exists():
        if wizard:
            config = _apply_workspace_override(load_config(config_path))
        else:
            console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
            console.print(
                "  [bold]y[/bold] = overwrite with defaults (existing values will be lost)"
            )
            console.print(
                "  [bold]N[/bold] = refresh config, keeping existing values and adding new fields"
            )
            if typer.confirm("Overwrite?"):
                config = _apply_workspace_override(Config())
                save_config(config, config_path)
                console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
            else:
                config = _apply_workspace_override(load_config(config_path))
                save_config(config, config_path)
                console.print(
                    f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)"
                )
    else:
        config = _apply_workspace_override(Config())
        # In wizard mode, don't save yet - the wizard will handle saving if should_save=True
        if not wizard:
            save_config(config, config_path)
            console.print(f"[green]✓[/green] Created config at {config_path}")

    # Run interactive wizard if enabled
    if wizard:
        from nanobot.cli.onboard import run_onboard

        try:
            result = run_onboard(initial_config=config)
            if not result.should_save:
                console.print("[yellow]Configuration discarded. No changes were saved.[/yellow]")
                return

            config = result.config
            save_config(config, config_path)
            console.print(f"[green]✓[/green] Config saved at {config_path}")
        except Exception as e:
            console.print(f"[red]✗[/red] Error during configuration: {e}")
            console.print("[yellow]Please run 'nanobot onboard' again to complete setup.[/yellow]")
            raise typer.Exit(1)
    _onboard_plugins(config_path)

    # Create workspace, preferring the configured workspace path.
    workspace_path = get_workspace_path(config.workspace_path)
    if not workspace_path.exists():
        workspace_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace_path}")

    sync_workspace_templates(workspace_path)

    agent_cmd = 'nanobot agent -m "Hello!"'
    gateway_cmd = "nanobot gateway"
    if config:
        agent_cmd += f" --config {config_path}"
        gateway_cmd += f" --config {config_path}"

    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    if wizard:
        console.print(f"  1. Chat: [cyan]{agent_cmd}[/cyan]")
        console.print(f"  2. Start gateway: [cyan]{gateway_cmd}[/cyan]")
    else:
        console.print(f"  1. Add your API key to [cyan]{config_path}[/cyan]")
        console.print("     Get one at: https://openrouter.ai/keys")
        console.print(f"  2. Chat: [cyan]{agent_cmd}[/cyan]")
    console.print(
        "\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]"
    )


def _merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Recursively fill in missing values from defaults without overwriting user config."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = _merge_missing_defaults(merged[key], value)
    return merged


def _onboard_plugins(config_path: Path) -> None:
    """Inject default config for all discovered channels (built-in + plugins)."""
    import json

    from nanobot.channels.registry import discover_all

    all_channels = discover_all()
    if not all_channels:
        return

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    channels = data.setdefault("channels", {})
    for name, cls in all_channels.items():
        if name not in channels:
            channels[name] = cls.default_config()
        else:
            channels[name] = _merge_missing_defaults(channels[name], cls.default_config())

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _model_display(config: Config) -> tuple[str, str]:
    """Return (resolved_model_name, preset_tag) for display strings."""
    resolved = config.resolve_preset()
    name = config.agents.defaults.model_preset
    tag = f" (preset: {name})" if name else ""
    return resolved.model, tag


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """Load config and optionally override the active workspace."""
    from nanobot.config.loader import load_config, resolve_config_env_vars, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")

    try:
        loaded = resolve_config_env_vars(load_config(config_path))
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    _warn_deprecated_config_keys(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def _warn_deprecated_config_keys(config_path: Path | None) -> None:
    """Hint users to remove obsolete keys from their config file."""
    import json

    from nanobot.config.loader import get_config_path

    path = config_path or get_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if "memoryWindow" in raw.get("agents", {}).get("defaults", {}):
        console.print(
            "[dim]Hint: `memoryWindow` in your config is no longer used "
            "and can be safely removed.[/dim]"
        )


def _migrate_cron_store(config: "Config") -> None:
    """One-time migration: move legacy global cron store into the workspace."""
    from nanobot.config.paths import get_cron_dir

    legacy_path = get_cron_dir() / "jobs.json"
    new_path = config.workspace_path / "cron" / "jobs.json"
    if legacy_path.is_file() and not new_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.move(str(legacy_path), str(new_path))


# ============================================================================
# OpenAI-Compatible API Server
# ============================================================================


@app.command()
def serve(
    port: int | None = typer.Option(None, "--port", "-p", help="API server port"),
    host: str | None = typer.Option(None, "--host", "-H", help="Bind address"),
    timeout: float | None = typer.Option(None, "--timeout", "-t", help="Per-request timeout (seconds)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show nanobot runtime logs"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the OpenAI-compatible API server (/v1/chat/completions)."""
    try:
        from aiohttp import web  # noqa: F401
    except ImportError:
        console.print("[red]aiohttp is required. Install with: pip install 'nanobot-ai[api]'[/red]")
        raise typer.Exit(1)

    from loguru import logger

    from nanobot.api.server import create_app
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.image_generation import image_gen_provider_configs
    from nanobot.session.manager import SessionManager

    if verbose:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    runtime_config = _load_runtime_config(config, workspace)
    api_cfg = runtime_config.api
    host = host if host is not None else api_cfg.host
    port = port if port is not None else api_cfg.port
    timeout = timeout if timeout is not None else api_cfg.timeout
    sync_workspace_templates(runtime_config.workspace_path)
    bus = MessageBus()
    session_manager = SessionManager(runtime_config.workspace_path)
    try:
        agent_loop = AgentLoop.from_config(
            runtime_config, bus,
            session_manager=session_manager,
            image_generation_provider_configs=image_gen_provider_configs(runtime_config),
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    model_name, preset_tag = _model_display(runtime_config)
    console.print(f"{__logo__} Starting OpenAI-compatible API server")
    console.print(f"  [cyan]Endpoint[/cyan] : http://{host}:{port}/v1/chat/completions")
    console.print(f"  [cyan]Model[/cyan]    : {model_name}{preset_tag}")
    console.print("  [cyan]Session[/cyan]  : api:default")
    console.print(f"  [cyan]Timeout[/cyan]  : {timeout}s")
    if host in {"0.0.0.0", "::"}:
        console.print(
            "[yellow]Warning:[/yellow] API is bound to all interfaces. "
            "Only do this behind a trusted network boundary, firewall, or reverse proxy."
        )
    console.print()

    api_app = create_app(agent_loop, model_name=model_name, request_timeout=timeout)

    async def on_startup(_app):
        await agent_loop._connect_mcp()

    async def on_cleanup(_app):
        await agent_loop.close_mcp()

    api_app.on_startup.append(on_startup)
    api_app.on_cleanup.append(on_cleanup)

    web.run_app(api_app, host=host, port=port, print=lambda msg: logger.info(msg))


# ============================================================================
# Gateway / Server
# ============================================================================


def _run_gateway(
    config: Config,
    *,
    port: int | None = None,
    open_browser_url: str | None = None,
    webui_static_dist: bool = True,
    webui_runtime_surface: str = "browser",
    webui_runtime_capabilities: dict[str, Any] | None = None,
    health_server_enabled: bool = True,
) -> None:
    """Shared gateway runtime; ``open_browser_url`` opens a tab once channels are up."""
    from nanobot.agent.tools.message import MessageTool
    from nanobot.bus.queue import MessageBus
    from nanobot.bus.runtime_events import RuntimeEventBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.bound_runner import run_bound_cron_job
    from nanobot.cron.service import CronJobSkippedError, CronService
    from nanobot.cron.session_turns import is_bound_cron_job
    from nanobot.cron.types import CronJob
    from nanobot.providers.factory import build_provider_snapshot, load_provider_snapshot
    from nanobot.providers.image_generation import image_gen_provider_configs
    from nanobot.session.manager import SessionManager
    from nanobot.session.webui_turns import WebuiTurnCoordinator
    from nanobot.webui.token_usage import TokenUsageHook

    port = port if port is not None else config.gateway.port

    console.print(f"{__logo__} Starting nanobot gateway version {__version__} on port {port}...")
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    runtime_events = RuntimeEventBus()
    try:
        provider_snapshot = build_provider_snapshot(config)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc
    session_manager = SessionManager(config.workspace_path)

    # Preserve existing single-workspace installs, but keep custom workspaces clean.
    if is_default_workspace(config.workspace_path):
        _migrate_cron_store(config)

    # Create cron service with workspace-scoped store
    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    agent = AgentLoop.from_config(
        config, bus,
        provider=provider_snapshot.provider,
        model=provider_snapshot.model,
        context_window_tokens=provider_snapshot.context_window_tokens,
        cron_service=cron,
        session_manager=session_manager,
        image_generation_provider_configs=image_gen_provider_configs(config),
        provider_snapshot_loader=load_provider_snapshot,
        runtime_events=runtime_events,
        provider_signature=provider_snapshot.signature,
        hooks=[TokenUsageHook(timezone_name=config.agents.defaults.timezone)],
    )
    WebuiTurnCoordinator(
        bus=bus,
        sessions=session_manager,
        schedule_background=lambda coro: agent._schedule_background(coro),
    ).subscribe(runtime_events)

    from nanobot.bus.events import OutboundMessage
    from nanobot.session.keys import session_key_for_channel

    def _channel_session_key(channel: str, chat_id: str) -> str:
        return session_key_for_channel(
            channel,
            chat_id,
            unified_session=config.agents.defaults.unified_session,
        )

    async def _deliver_to_channel(
        msg: OutboundMessage, *, record: bool = False, session_key: str | None = None,
    ) -> None:
        """Publish a user-visible message and mirror it into that channel's session."""
        metadata = dict(msg.metadata or {})
        record = record or bool(metadata.pop("_record_channel_delivery", False))
        if metadata != (msg.metadata or {}):
            msg = OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=msg.content,
                reply_to=msg.reply_to,
                media=msg.media,
                metadata=metadata,
                buttons=msg.buttons,
            )
        if (
            record
            and msg.channel != "cli"
            and msg.content.strip()
            and hasattr(session_manager, "get_or_create")
            and hasattr(session_manager, "save")
        ):
            key = session_key or _channel_session_key(msg.channel, msg.chat_id)
            session = session_manager.get_or_create(key)
            extra: dict[str, Any] = {"_channel_delivery": True}
            if msg.media:
                extra["media"] = list(msg.media)
            session.add_message("assistant", msg.content, **extra)
            session_manager.save(session)
        await bus.publish_outbound(msg)

    message_tool = getattr(agent, "tools", {}).get("message")
    if isinstance(message_tool, MessageTool):
        message_tool.set_send_callback(_deliver_to_channel)

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        async def _silent(*_args, **_kwargs):
            pass

        # Dream is an internal job — run directly, not through the agent loop.
        if job.name == "dream":
            from nanobot.agent.memory import MemoryStore

            dream_session_key = MemoryStore.dream_session_key
            build_dream_commit_message = MemoryStore.build_dream_commit_message
            prune_dream_sessions = MemoryStore.prune_dream_sessions

            store = agent.context.memory
            resp = None
            try:
                result = store.build_dream_prompt()
                if result is None:
                    logger.info("Dream: nothing to process")
                    return None
                prompt, last_cursor = result
                key = dream_session_key()
                resp = await agent.process_direct(
                    prompt,
                    session_key=key,
                    ephemeral=True,
                    tools=store.build_dream_tools(),
                    on_progress=_silent,
                )
                if MemoryStore.dream_run_completed(resp):
                    store.set_last_dream_cursor(last_cursor)
                    logger.info("Dream cron job completed, cursor advanced to {}", last_cursor)
                else:
                    logger.warning(
                        "Dream cron job did not complete; cursor remains at {}",
                        store.get_last_dream_cursor(),
                    )
            except Exception:
                logger.exception("Dream cron job failed")
            finally:
                from nanobot.webui.token_usage import record_response_token_usage

                record_response_token_usage(
                    resp,
                    source="dream",
                    timezone_name=config.agents.defaults.timezone,
                )
                if store.git.is_initialized():
                    msg = build_dream_commit_message(
                        "dream: periodic memory consolidation", resp,
                    )
                    sha = store.git.auto_commit(msg)
                    if sha:
                        logger.info("Dream commit: {}", sha)
                store.compact_history()
                prune_dream_sessions(agent.sessions.sessions_dir)
            return None

        # Heartbeat is a system job that checks HEARTBEAT.md for active tasks.
        if job.name == "heartbeat":
            heartbeat_file = config.workspace_path / "HEARTBEAT.md"
            try:
                content = heartbeat_file.read_text(encoding="utf-8")
            except OSError:
                logger.debug("Heartbeat: HEARTBEAT.md missing")
                return None
            if not _heartbeat_has_active_tasks(content):
                logger.debug("Heartbeat: HEARTBEAT.md has no active tasks")
                return None

            channel, chat_id = _pick_heartbeat_target()
            if channel == "cli":
                return None

            prompt = (
                _HEARTBEAT_PREAMBLE
                + f"Review the following HEARTBEAT.md and report any active tasks:\n\n{content}"
            )

            # Internal check: funnel all output through the post-run gate so the
            # turn can't deliver directly via the message tool and skip it.
            suppress_token = None
            if isinstance(message_tool, MessageTool):
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
                if isinstance(message_tool, MessageTool) and suppress_token is not None:
                    message_tool.reset_suppress_delivery(suppress_token)
            response = resp.content if resp else ""

            # Keep a small tail of heartbeat history so the loop stays bounded.
            session = agent.sessions.get_or_create("heartbeat")
            session.retain_recent_legal_suffix(hb_cfg.keep_recent_messages)
            agent.sessions.save(session)

            if not response:
                return None

            # Fail closed: stay silent on evaluator failure instead of notifying.
            should_notify = await evaluate_response(
                response, prompt, agent.provider, agent.model,
                default_notify=False,
            )
            if should_notify:
                logger.info("Heartbeat: completed, delivering response")
                await _deliver_to_channel(
                    OutboundMessage(channel=channel, chat_id=chat_id, content=response),
                    record=True,
                )
            else:
                logger.info("Heartbeat: silenced by post-run evaluation")
            return response

        if is_bound_cron_job(job):
            return await run_bound_cron_job(job, agent=agent, cron=cron)

        reason = "unbound agent cron job must be recreated from a chat session"
        logger.warning(
            "Cron: skipped unbound agent job '{}' ({}): {}",
            job.name,
            job.id,
            reason,
        )
        raise CronJobSkippedError(reason)

    cron.on_job = on_cron_job

    def _webui_runtime_model_name() -> str | None:
        model = getattr(agent, "model", None)
        if isinstance(model, str):
            stripped = model.strip()
            return stripped or None
        return None

    # Create channel manager (forwards SessionManager so the WebSocket channel
    # can serve the embedded webui's REST surface).
    channels = ChannelManager(
        config,
        bus,
        session_manager=session_manager,
        cron_service=cron,
        webui_runtime_model_name=_webui_runtime_model_name,
        webui_cron_pending_job_ids=getattr(agent, "pending_cron_job_ids_for_session", None),
        webui_static_dist=webui_static_dist,
        webui_runtime_surface=webui_runtime_surface,
        webui_runtime_capabilities=webui_runtime_capabilities,
    )

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        sidebar_state = read_webui_sidebar_state()
        return _pick_heartbeat_target_from_sessions(
            enabled_channels=channels.enabled_channels,
            sessions=session_manager.list_sessions(),
            archived_keys=sidebar_state.get("archived_keys", []),
        )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    hb_cfg = config.gateway.heartbeat
    if hb_cfg.enabled:
        console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")
    else:
        console.print("[yellow]✗[/yellow] Heartbeat: disabled")

    async def _customer_bot_download_media(message: dict) -> list[str]:
        """Download photo/document/video from a customer bot message. Returns local file paths."""
        import os as _os
        import urllib.request as _req
        import json as _j
        token = _os.environ.get("FOOLISH_CUSTOMER_BOT_TOKEN", "")
        if not token:
            return []
        # Pick the best file_id from the message
        file_id: str | None = None
        ext = ".bin"
        if message.get("photo"):
            # photos is an array of PhotoSize; take the last (highest resolution)
            photo = message["photo"][-1]
            file_id = photo.get("file_id")
            ext = ".jpg"
        elif message.get("document"):
            doc = message["document"]
            file_id = doc.get("file_id")
            mime = doc.get("mime_type", "")
            ext = "." + mime.split("/")[-1] if mime and "/" in mime else ".bin"
        elif message.get("video"):
            file_id = message["video"].get("file_id")
            ext = ".mp4"
        if not file_id:
            return []
        try:
            # Resolve file_path via getFile
            get_file_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None, lambda: _req.urlopen(get_file_url, timeout=10)
            )
            data = _j.loads(res.read())
            file_path = data.get("result", {}).get("file_path")
            if not file_path:
                return []
            download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            # Save to media dir
            from nanobot.config.paths import get_media_dir
            media_dir = get_media_dir("foolish_customer_bot")
            unique_id = file_id[-16:]
            local_path = str(media_dir / f"{unique_id}{ext}")
            await loop.run_in_executor(
                None,
                lambda: open(local_path, "wb").write(_req.urlopen(download_url, timeout=30).read()),
            )
            return [local_path]
        except Exception as e:
            logger.warning("_customer_bot_download_media failed: {}", e)
            return []

    async def _vision_describe_images(media_paths: list[str]) -> str:
        """Describe images via shared vision chain (HF Qwen3-VL → OpenRouter → Anthropic)."""
        from nanobot.providers.vision_chain import describe_images
        return await describe_images(media_paths)

    async def _customer_bot_send(chat_id: str, text: str) -> None:
        """Send a message to a customer via @the_foolish_butcher_bot."""
        import os as _os
        import urllib.request as _req
        import urllib.parse as _up
        token = _os.environ.get("FOOLISH_CUSTOMER_BOT_TOKEN", "")
        if not token:
            logger.warning("FOOLISH_CUSTOMER_BOT_TOKEN not set — cannot send to customer")
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = _up.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: _req.urlopen(url, payload, timeout=10))
        except Exception as e:
            logger.error("customer_bot_send failed: {}", e)

    async def _get_order_ref_from_stripe_session(stripe_session_id: str) -> str | None:
        """Resolve a Stripe checkout session ID to a Foolish orderRef via the storefront API."""
        import os as _os
        import urllib.request as _req
        import urllib.parse as _up
        import json as _j
        storefront_url = _os.environ.get("FOOLISH_WOO_BASE_URL", "https://thefoolishbutcher.com").rstrip("/")
        url = f"{storefront_url}/api/stripe/session?session_id={_up.quote(stripe_session_id)}"
        try:
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: _req.urlopen(url, timeout=10))
            data = _j.loads(res.read())
            return data.get("orderRef") or None
        except Exception as e:
            logger.error("_get_order_ref_from_stripe_session failed: {}", e)
            return None

    async def _cms_get_order_by_ref(order_ref: str) -> dict | None:
        """Fetch a Foolish order from Payload CMS by orderNumber."""
        import os as _os
        import urllib.request as _req
        cms_url = _os.environ.get("FOOLISH_PAYLOAD_URL", "https://cms-production-1dda.up.railway.app")
        secret = _os.environ.get("FOOLISH_PAYLOAD_SECRET", "")
        url = f"{cms_url}/api/orders?where[orderNumber][equals]={order_ref}&limit=1"
        try:
            loop = asyncio.get_event_loop()
            req = _req.Request(url, headers={"x-storefront-secret": secret})
            res = await loop.run_in_executor(None, lambda: _req.urlopen(req, timeout=10))
            import json as _j
            data = _j.loads(res.read())
            docs = data.get("docs", [])
            return docs[0] if docs else None
        except Exception as e:
            logger.error("cms_get_order_by_ref failed: {}", e)
            return None

    async def _cms_patch_order(order_id: str, fields: dict) -> bool:
        """PATCH an order in Payload CMS."""
        import os as _os, json as _j, urllib.request as _req
        cms_url = _os.environ.get("FOOLISH_PAYLOAD_URL", "https://cms-production-1dda.up.railway.app")
        secret = _os.environ.get("FOOLISH_PAYLOAD_SECRET", "")
        # Need admin login for PATCH — use stored credentials
        email = _os.environ.get("FOOLISH_PAYLOAD_EMAIL", "")
        password = _os.environ.get("FOOLISH_PAYLOAD_PASSWORD", "")
        try:
            loop = asyncio.get_event_loop()
            # Login
            login_data = _j.dumps({"email": email, "password": password}).encode()
            login_req = _req.Request(
                f"{cms_url}/api/users/login",
                data=login_data,
                headers={"Content-Type": "application/json"},
            )
            login_res = await loop.run_in_executor(None, lambda: _req.urlopen(login_req, timeout=10))
            token = _j.loads(login_res.read()).get("token", "")
            # PATCH
            patch_data = _j.dumps(fields).encode()
            patch_req = _req.Request(
                f"{cms_url}/api/orders/{order_id}",
                data=patch_data,
                method="PATCH",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            )
            await loop.run_in_executor(None, lambda: _req.urlopen(patch_req, timeout=10))
            return True
        except Exception as e:
            logger.error("cms_patch_order failed: {}", e)
            return False

    async def _handle_customer_bot_update(update: dict) -> None:
        """Route incoming Telegram updates from @the_foolish_butcher_bot."""
        import os as _os
        message = update.get("message") or update.get("callback_query", {}).get("message")
        if not message:
            return
        chat_id = str(message["chat"]["id"])
        text = message.get("text", "") or message.get("caption", "")
        customer_name = message["chat"].get("first_name", "")
        # Detect media (photos, documents, videos)
        has_media = bool(message.get("photo") or message.get("document") or message.get("video"))

        # --- /start order_XXXXX  →  link customer to order ---
        if text.startswith("/start"):
            parts = text.split()
            payload_param = parts[1] if len(parts) > 1 else ""
            if payload_param.startswith("order_") or payload_param.startswith("session_"):
                # order_FOOLISH-XXX or session_cs_live_XXX (fallback via Stripe session)
                order_ref = payload_param[6:] if payload_param.startswith("order_") else None
                stripe_session = payload_param[8:] if payload_param.startswith("session_") else None
                order = await _cms_get_order_by_ref(order_ref) if order_ref else None
                if not order and stripe_session:
                    order_ref = await _get_order_ref_from_stripe_session(stripe_session)
                    if order_ref:
                        order = await _cms_get_order_by_ref(order_ref)
                if order:
                    await _cms_patch_order(str(order["id"]), {"customerTelegramId": chat_id})
                    await _customer_bot_send(
                        chat_id,
                        f"Ciao {customer_name}.\n\n"
                        f"Ordine <b>{order_ref}</b> collegato.\n"
                        f"Da qui ti aggiorno su spedizione e tracking. Se hai domande, scrivimi.\n\n"
                        f"— Frank, The Foolish Butcher",
                    )
                    # Notify Alessandro
                    tg_allow = (config.channels.telegram.get("allowFrom") or []) if isinstance(config.channels.telegram, dict) else []
                    alessandros_chat = str(tg_allow[0]) if tg_allow else ""
                    if alessandros_chat:
                        asyncio.create_task(_deliver_to_channel(
                            OutboundMessage(
                                channel="telegram",
                                chat_id=alessandros_chat,
                                content=f"✅ Cliente collegato — {customer_name} è ora su Telegram per l'ordine {order_ref}",
                            )
                        ))
                else:
                    # Order not found — let Frank handle it conversationally
                    text = f"[primo contatto — ordine non trovato per ref: {order_ref or stripe_session}] Ciao, sono {customer_name}."
                    # falls through to the free-message handler below
            else:
                # /start with no payload — open conversation
                text = f"[primo contatto — nessun riferimento ordine] Ciao, sono {customer_name}."
                # falls through to the free-message handler below
            if text.startswith("/start"):
                return  # order was found and handled above, nothing left to do

        # --- Free message → route through Frank as Foolish Butcher ---
        alessandros_chat = ""
        tg_allow = (config.channels.telegram.get("allowFrom") or []) if isinstance(config.channels.telegram, dict) else []
        if tg_allow:
            alessandros_chat = str(tg_allow[0])

        # The Frank persona and tone are defined in the always-loaded skill
        # `foolish-customer-bot`. Pass only the raw customer message so Frank
        # responds AS Frank TO the customer, not back to Alessandro.
        # Download any media the customer sent so Frank can see it.
        media_paths: list[str] = []
        if has_media:
            media_paths = await _customer_bot_download_media(message)

        # Describe images via vision chain (HF → OpenRouter → Anthropic) so Frank
        # gets a text description regardless of his underlying text-only model.
        image_description = ""
        if media_paths:
            image_description = await _vision_describe_images(media_paths)

        media_hint = ""
        if image_description:
            media_hint = f"\n[Immagine inviata dal cliente — descrizione automatica: {image_description}]"
        elif media_paths:
            media_hint = f"\n[Il cliente ha allegato {len(media_paths)} file — descrizione non disponibile]"

        customer_context = (
            f"[canale: foolish_customer_bot | cliente: {customer_name} | chat_id: {chat_id}]\n"
            f"{text}{media_hint}"
        )
        session_key = f"foolish_customer:{chat_id}"
        try:
            response = await asyncio.wait_for(
                agent.process_direct(
                    customer_context,
                    session_key=session_key,
                    channel="foolish_customer_bot",
                    chat_id=chat_id,
                ),
                timeout=30.0,
            )
            proposed = response.content if response else "Messaggio ricevuto, ti rispondo a breve."
        except Exception:
            proposed = "Messaggio ricevuto. Ti rispondo a breve."

        # --- Approval flow (same pattern as WhatsApp) ---
        # Save pending state per-customer, notify Alessandro, do NOT reply to customer yet.
        import os as _os, json as _json_mod
        pending_dir = _os.path.expanduser("~/.nanobot/memory")
        _os.makedirs(pending_dir, exist_ok=True)
        pending_path = _os.path.join(pending_dir, f"fb_pending_{chat_id.replace(':', '_')}.json")
        with open(pending_path, "w", encoding="utf-8") as _f:
            _json_mod.dump({
                "chat_id": chat_id,
                "proposed": proposed,
                "customer_message": text,
                "customer_name": customer_name,
                "media_paths": media_paths,
            }, _f, ensure_ascii=False, indent=2)

        short_id = chat_id[-4:] if len(chat_id) >= 4 else chat_id
        if alessandros_chat:
            asyncio.create_task(_deliver_to_channel(
                OutboundMessage(
                    channel="telegram",
                    chat_id=alessandros_chat,
                    content=(
                        f"💬 Foolish Bot — {customer_name} (#{short_id})\n\n"
                        f"Messaggio:\n{text or '[nessun testo]'}\n\n"
                        f"💡 Proposta Frank:\n{proposed}\n\n"
                        f"Rispondi:\n"
                        f"• \"fb ok\" → invio la proposta\n"
                        f"• \"fb [testo]\" → invio il testo che scrivi\n"
                        f"• \"fb ignora\" → non rispondo"
                    ),
                    media=media_paths if media_paths else None,
                )
            ))

    async def _health_server(host: str, health_port: int):
        """Lightweight HTTP health endpoint on the gateway port."""
        import json as _json
        import hmac as _hmac_mod
        import hashlib as _hashlib
        import collections as _collections
        import time as _time_rl

        # ── Webhook security helpers ──────────────────────────────────────────
        _rate_buckets: dict = _collections.defaultdict(lambda: _collections.deque())
        _RATE_LIMIT = 30    # max requests per IP per 60-second window
        _RATE_WINDOW = 60.0

        def _check_rate_limit(ip: str) -> bool:
            now = _time_rl.monotonic()
            bucket = _rate_buckets[ip]
            while bucket and now - bucket[0] > _RATE_WINDOW:
                bucket.popleft()
            if len(bucket) >= _RATE_LIMIT:
                return False
            bucket.append(now)
            return True

        def _parse_http_headers(raw: bytes) -> dict:
            """Return lowercase header dict from raw HTTP request bytes."""
            section = raw.split(b"\r\n\r\n", 1)[0]
            result = {}
            for line in section.decode("utf-8", errors="replace").splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    result[k.strip().lower()] = v.strip()
            return result

        def _verify_hmac(body: bytes, sig_header: str, secret: str) -> bool:
            """Verify HMAC-SHA256 signature.
            sig_header may be 'sha256=<hex>' or bare '<hex>'.
            Returns True (skip verification) if secret is empty."""
            if not secret:
                return True
            if not sig_header:
                return False
            expected = _hmac_mod.new(secret.encode(), body, _hashlib.sha256).hexdigest()
            actual = sig_header.lower().removeprefix("sha256=").strip()
            return _hmac_mod.compare_digest(expected, actual)

        async def handle(reader, writer):
            try:
                data = await asyncio.wait_for(reader.read(65536), timeout=5)
            except (asyncio.TimeoutError, ConnectionError):
                writer.close()
                return

            request_line = data.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
            method, path = "", ""
            parts = request_line.split(" ")
            if len(parts) >= 2:
                method, path = parts[0], parts[1]

            peer = writer.get_extra_info("peername")
            peer_ip = peer[0] if peer else "unknown"

            if method == "POST" and not _check_rate_limit(peer_ip):
                logger.warning("webhook rate limit exceeded from {}", peer_ip)
                _rl_body = _json.dumps({"error": "Too Many Requests"})
                writer.write(
                    f"HTTP/1.0 429 Too Many Requests\r\nContent-Type: application/json\r\n"
                    f"Retry-After: 60\r\nContent-Length: {len(_rl_body)}\r\n\r\n{_rl_body}".encode()
                )
                await writer.drain()
                writer.close()
                return

            if method == "GET" and path == "/health":
                body = _json.dumps({"status": "ok"})
                resp = (
                    f"HTTP/1.0 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"\r\n{body}"
                )
            elif method == "GET" and (path == "/logs" or path.startswith("/logs?") or path.startswith("/logs/")):
                import os as _os
                import urllib.parse as _urlparse

                _parsed = _urlparse.urlparse(path)
                _qs = _urlparse.parse_qs(_parsed.query)
                _logs_token = _os.environ.get("FRANK_LOGS_TOKEN", "")
                _req_token = (_qs.get("token") or [""])[0]

                if _logs_token and _req_token != _logs_token:
                    _b = "Unauthorized"
                    resp = (
                        f"HTTP/1.0 401 Unauthorized\r\nContent-Type: text/plain\r\n"
                        f"Content-Length: {len(_b)}\r\n\r\n{_b}"
                    )
                elif _parsed.path == "/logs/data":
                    # JSON endpoint — last N lines, optional level filter
                    _level_filter = (_qs.get("level") or [""])[0].upper()
                    _n = int((_qs.get("n") or ["500"])[0])
                    _log_path = _os.path.join(
                        _os.path.dirname(_os.path.abspath(__file__)),
                        "../../../.nanobot/frank.log",
                    )
                    _log_path = _os.path.normpath(_log_path)
                    try:
                        with open(_log_path, "rb") as _lf:
                            _lf.seek(0, 2)
                            _size = _lf.tell()
                            _chunk = min(_size, 256 * 1024)
                            _lf.seek(_size - _chunk)
                            _raw = _lf.read().decode("utf-8", errors="replace")
                        _all_lines = _raw.splitlines()[-_n:]
                        if _level_filter and _level_filter != "ALL":
                            _all_lines = [_line for _line in _all_lines if f"| {_level_filter}" in _line or f"| {_level_filter.lower()}" in _line]
                        body = _json.dumps({"lines": _all_lines, "total": len(_all_lines)})
                    except Exception as _e:
                        body = _json.dumps({"lines": [], "error": str(_e)})
                    resp = (
                        f"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n"
                        f"Access-Control-Allow-Origin: *\r\n"
                        f"Content-Length: {len(body.encode())}\r\n\r\n{body}"
                    )
                elif _parsed.path == "/logs/manifest.json":
                    _manifest = _json.dumps({
                        "name": "Frank Logs",
                        "short_name": "Frank",
                        "start_url": f"/logs?token={_logs_token}",
                        "display": "standalone",
                        "background_color": "#0d1117",
                        "theme_color": "#0d1117",
                        "icons": [{"src": "https://fav.farm/🐈", "sizes": "192x192", "type": "image/png"}],
                    })
                    resp = (
                        f"HTTP/1.0 200 OK\r\nContent-Type: application/manifest+json\r\n"
                        f"Content-Length: {len(_manifest.encode())}\r\n\r\n{_manifest}"
                    )
                else:
                    _tok_param = f"?token={_logs_token}" if _logs_token else ""
                    _html_page = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0d1117">
<link rel="manifest" href="/logs/manifest.json">
<title>Frank Logs</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#c9d1d9;font-family:'SF Mono',monospace;font-size:12px;overflow-x:hidden}}
#header{{position:sticky;top:0;background:#161b22;border-bottom:1px solid #30363d;padding:10px 12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;z-index:10}}
#header h1{{font-size:14px;font-weight:600;color:#f0f6fc;flex:1}}
.dot{{width:8px;height:8px;border-radius:50%;background:#3fb950;display:inline-block}}
.dot.off{{background:#6e7681}}
button{{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer}}
button.active{{background:#1f6feb;border-color:#1f6feb;color:#fff}}
#log{{padding:8px 12px;padding-bottom:80px}}
.line{{padding:2px 0;border-bottom:1px solid #0d1117;white-space:pre-wrap;word-break:break-all;line-height:1.5}}
.ERROR{{color:#ff7b72}}.WARNING{{color:#d29922}}.INFO{{color:#8b949e}}.other{{color:#c9d1d9}}
#bottom{{position:fixed;bottom:0;left:0;right:0;background:#161b22;border-top:1px solid #30363d;padding:8px 12px;display:flex;gap:6px;align-items:center}}
#status{{font-size:11px;color:#8b949e;flex:1}}
#scroll-btn{{background:#238636;border-color:#2ea043;color:#fff}}
</style>
</head>
<body>
<div id="header">
  <span class="dot" id="dot"></span>
  <h1>🐈 Frank Logs</h1>
  <button onclick="setFilter('ALL')" id="f-ALL" class="active">Tutti</button>
  <button onclick="setFilter('ERROR')" id="f-ERROR">Error</button>
  <button onclick="setFilter('WARNING')" id="f-WARNING">Warn</button>
  <button onclick="setFilter('INFO')" id="f-INFO">Info</button>
</div>
<div id="log"></div>
<div id="bottom">
  <span id="status">Caricamento...</span>
  <button id="scroll-btn" onclick="scrollToBottom()">↓ Fine</button>
</div>
<script>
let filter='ALL', atBottom=true, lines=[];
const logEl=document.getElementById('log');
const dot=document.getElementById('dot');
const status=document.getElementById('status');
const token=new URLSearchParams(location.search).get('token')||'';

function setFilter(f){{
  filter=f;
  document.querySelectorAll('[id^=f-]').forEach(b=>b.classList.remove('active'));
  document.getElementById('f-'+f).classList.add('active');
  render();
}}

function classify(line){{
  if(line.includes('| ERROR'))return 'ERROR';
  if(line.includes('| WARNING'))return 'WARNING';
  if(line.includes('| INFO'))return 'INFO';
  return 'other';
}}

function render(){{
  const filtered=filter==='ALL'?lines:lines.filter(l=>classify(l)===filter);
  logEl.innerHTML=filtered.map(l=>
    `<div class="line ${{classify(l)}}">${{l.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}}</div>`
  ).join('');
  if(atBottom)scrollToBottom();
  status.textContent=filtered.length+' righe';
}}

function scrollToBottom(){{
  window.scrollTo(0,document.body.scrollHeight);
}}

window.addEventListener('scroll',()=>{{
  atBottom=(window.innerHeight+window.scrollY)>=document.body.scrollHeight-50;
}});

async function refresh(){{
  try{{
    const r=await fetch('/logs/data?n=600&level='+filter+(token?'&token='+token:''));
    const d=await r.json();
    if(d.lines){{lines=d.lines;render();}}
    dot.className='dot';
  }}catch(e){{dot.className='dot off';}}
}}

refresh();
setInterval(refresh,5000);

if('serviceWorker' in navigator){{
  navigator.serviceWorker.register('/logs/sw.js').catch(()=>{{}});
}}
</script>
</body>
</html>"""
                    resp = (
                        f"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                        f"Content-Length: {len(_html_page.encode())}\r\n\r\n{_html_page}"
                    )
            elif method == "POST" and path == "/hooks/foolish-storefront-order":
                import os as _os
                _hdr_end = data.find(b"\r\n\r\n")
                body_bytes = data[_hdr_end + 4:] if _hdr_end != -1 else b""
                _sf_secret = _os.environ.get("FOOLISH_STOREFRONT_WH_SECRET", "")
                _sf_sig = _parse_http_headers(data).get("x-foolish-signature", "")
                if not _verify_hmac(body_bytes, _sf_sig, _sf_secret):
                    logger.warning("foolish-storefront-order: invalid signature from {}", peer_ip)
                    _body401 = _json.dumps({"error": "Unauthorized"})
                    writer.write(
                        f"HTTP/1.0 401 Unauthorized\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(_body401)}\r\n\r\n{_body401}".encode()
                    )
                    await writer.drain()
                    writer.close()
                    return
                try:
                    order = _json.loads(body_bytes.decode("utf-8", errors="replace"))

                    items = []
                    try:
                        items = _json.loads(order.get("itemsJson") or "[]")
                    except Exception:
                        pass

                    items_text = "\n".join(
                        f"  • {i.get('name', '?')} ({i.get('variantLabel', '')}) "
                        f"× {i.get('qty', 1)} — {float(i.get('price', 0)) * int(i.get('qty', 1)):.2f}€"
                        for i in items
                    ) if items else "  (dettagli non disponibili)"

                    telegram_cfg = config.channels.telegram
                    tg_allow = (telegram_cfg.get("allowFrom") or []) if isinstance(telegram_cfg, dict) else (getattr(telegram_cfg, "allow_from", None) or [])
                    chat_id = str(tg_allow[0]) if tg_allow else ""

                    # Scrivi scribble in memoria per consapevolezza futura
                    _order_ref = order.get('externalRef') or order.get('stripeSessionId', 'N/A')
                    _customer = f"{order.get('customerName', 'N/A')} <{order.get('customerEmail', 'N/A')}>"
                    _amount = f"{order.get('amount', 0):.2f} {order.get('currency', 'EUR')}"
                    _cms_ok = "✅ registrato nel CMS" if not order.get('cmsError') else "🚨 NON registrato nel CMS"
                    _scribble_dir = _pathlib.Path("/home/ab/.nanobot/memory/scribble")
                    _scribble_dir.mkdir(parents=True, exist_ok=True)
                    _today = _datetime.datetime.now().strftime("%Y-%m-%d")
                    _scribble_path = _scribble_dir / f"ordini-{_today}.md"
                    _scribble_line = (
                        f"- [{_datetime.datetime.now().strftime('%H:%M')}] Ordine {_order_ref} — "
                        f"{_customer} — {_amount} — {_cms_ok}\n"
                        f"  Prodotti: {items_text.strip()}\n"
                    )
                    try:
                        with open(_scribble_path, "a") as _f:
                            _f.write(_scribble_line)
                    except Exception as _e:
                        logger.warning("foolish-storefront-order: scribble write failed: {}", _e)

                    if chat_id:
                        cms_error = order.get("cmsError")
                        if cms_error:
                            msg_text = (
                                f"🚨 ORDINE NON SALVATO NEL CMS — intervento manuale richiesto\n\n"
                                f"Ordine: {_order_ref}\n"
                                f"Cliente: {order.get('customerName', 'N/A')} ({order.get('customerEmail', 'N/A')})\n"
                                f"Totale: {_amount}\n\n"
                                f"Prodotti:\n{items_text}\n\n"
                                f"⚠️ Il pagamento Stripe è andato a buon fine ma la registrazione nel CMS ha fallito dopo 4 tentativi.\n"
                                f"Errore: {cms_error[:300]}"
                            )
                            logger.error("foolish-storefront-order: CMS creation failed for {}", _order_ref)
                        else:
                            msg_text = (
                                f"🛒 Nuovo ordine — {_order_ref}\n\n"
                                f"Cliente: {order.get('customerName', 'N/A')} "
                                f"({order.get('customerEmail', 'N/A')})\n"
                                f"Totale: {_amount}\n\n"
                                f"Prodotti:\n{items_text}"
                            )
                        asyncio.create_task(_deliver_to_channel(
                            OutboundMessage(channel="telegram", chat_id=chat_id, content=msg_text),
                        ))
                        logger.info("foolish-storefront-order hook: notified telegram {} cmsError={}", chat_id, bool(cms_error))

                    # Schedula verifica pipeline a +5 min (one-shot, delete_after_run)
                    try:
                        from nanobot.cron.types import CronSchedule as _CronSchedule
                        import time as _time
                        _check_at_ms = int(_time.time() * 1000) + 5 * 60 * 1000
                        _cms_url = os.environ.get("FOOLISH_PAYLOAD_URL", "https://cms-production-1dda.up.railway.app")
                        _check_msg = (
                            f"Verifica pipeline ordine {_order_ref} (appena notificato ad Alessandro).\n\n"
                            f"Cliente: {_customer} | Totale: {_amount}\n"
                            f"CMS registrato: {_cms_ok}\n\n"
                            f"Esegui questi controlli:\n"
                            f"1. CMS — GET {_cms_url}/api/orders?where[orderNumber][equals]={_order_ref} "
                            f"con header x-storefront-secret. Verifica che l'ordine esista e abbia "
                            f"customerEmail, total, lineItems corretti.\n"
                            f"2. Railway logs — controlla i log del servizio storefront negli ultimi 10 min "
                            f"per errori relativi a questo ordine o al webhook Stripe.\n"
                            f"3. Se tutto ok: scrivi una riga in "
                            f"/home/ab/.nanobot/memory/scribble/ordini-{_today}.md con '  ✅ pipeline verificata' "
                            f"e non mandare nessun messaggio.\n"
                            f"4. Se qualcosa non va: notifica subito su Telegram 8273632991 con i dettagli."
                        )
                        cron.add_job(
                            name=f"order-check-{_order_ref}",
                            schedule=_CronSchedule(kind="at", at_ms=_check_at_ms),
                            message=_check_msg,
                            deliver=True,
                            channel="telegram",
                            to=chat_id,
                            channel_meta={
                                "user_id": int(chat_id) if chat_id.isdigit() else 0,
                                "username": "ale_boss_live",
                                "first_name": "Alessandro",
                                "is_group": False,
                                "message_thread_id": None,
                                "is_forum": False,
                                "reply_to_message_id": None,
                                "_wants_stream": False,
                            },
                            session_key=f"telegram:{chat_id}",
                            delete_after_run=True,
                        )
                        logger.info("foolish-storefront-order: scheduled pipeline check for {}", _order_ref)
                    except Exception as _ce:
                        logger.warning("foolish-storefront-order: could not schedule check: {}", _ce)

                    body = _json.dumps({"ok": True})
                    resp = (
                        f"HTTP/1.0 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
                except Exception as _exc:
                    logger.exception("foolish-storefront-order hook error")
                    body = _json.dumps({"error": str(_exc)})
                    resp = (
                        f"HTTP/1.0 500 Internal Server Error\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
            elif method == "POST" and path == "/hooks/foolish-pro-register":
                import os as _os
                _hdr_end = data.find(b"\r\n\r\n")
                body_bytes = data[_hdr_end + 4:] if _hdr_end != -1 else b""
                _sf_secret = _os.environ.get("FOOLISH_STOREFRONT_WH_SECRET", "")
                _sf_sig = _parse_http_headers(data).get("x-foolish-signature", "")
                if not _verify_hmac(body_bytes, _sf_sig, _sf_secret):
                    logger.warning("foolish-pro-register: invalid signature from {}", peer_ip)
                    _body401 = _json.dumps({"error": "Unauthorized"})
                    writer.write(
                        f"HTTP/1.0 401 Unauthorized\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(_body401)}\r\n\r\n{_body401}".encode()
                    )
                    await writer.drain()
                    writer.close()
                    return
                try:
                    pro = _json.loads(body_bytes.decode("utf-8", errors="replace"))

                    # Notify Alessandro
                    tg_allow = (config.channels.telegram.get("allowFrom") or []) if isinstance(config.channels.telegram, dict) else []
                    ale_chat = str(tg_allow[0]) if tg_allow else ""
                    if ale_chat:
                        asyncio.create_task(_deliver_to_channel(
                            OutboundMessage(
                                channel="telegram",
                                chat_id=ale_chat,
                                content=(
                                    f"🏷️ Nuovo Foolish Pro — {pro.get('businessName', 'N/A')}\n\n"
                                    f"Contatto: {pro.get('contactName', 'N/A')}\n"
                                    f"Email: {pro.get('email', 'N/A')}\n"
                                    f"P.IVA: {pro.get('vatNumber', 'N/A')}\n"
                                    f"Telegram: {pro.get('telegramUsername') or 'non fornito'}\n"
                                    f"Codice: {pro.get('discountCode', 'N/A')}"
                                ),
                            )
                        ))

                    # Send welcome message to customer via customer bot if telegram username known
                    tg_username = pro.get('telegramUsername') or ''
                    if tg_username:
                        # Can't DM by username directly — Frank will note it and follow up when they write
                        logger.info("pro-register: customer {} has telegram {}", pro.get('contactName'), tg_username)

                    body = _json.dumps({"ok": True})
                    resp = (
                        f"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n\r\n{body}"
                    )
                except Exception as _exc:
                    logger.exception("foolish-pro-register hook error")
                    body = _json.dumps({"error": str(_exc)})
                    resp = (
                        f"HTTP/1.0 500 Internal Server Error\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n\r\n{body}"
                    )
            elif method == "POST" and path == "/hooks/customer-telegram":
                import os as _os
                wh_secret = _os.environ.get("FOOLISH_CUSTOMER_WH_SECRET", "")
                # Verify secret from header
                raw_headers = data.split(b"\r\n\r\n", 1)[0].decode("utf-8", errors="replace")
                incoming_secret = ""
                for hline in raw_headers.splitlines()[1:]:
                    if hline.lower().startswith("x-telegram-bot-api-secret-token:"):
                        incoming_secret = hline.split(":", 1)[1].strip()
                        break
                if wh_secret and incoming_secret != wh_secret:
                    body = "Unauthorized"
                    resp = f"HTTP/1.0 401 Unauthorized\r\nContent-Length: {len(body)}\r\n\r\n{body}"
                else:
                    try:
                        header_end = data.find(b"\r\n\r\n")
                        body_bytes = data[header_end + 4:] if header_end != -1 else b""
                        update = _json.loads(body_bytes.decode("utf-8", errors="replace"))
                        asyncio.create_task(_handle_customer_bot_update(update))
                        body = _json.dumps({"ok": True})
                        resp = (
                            f"HTTP/1.0 200 OK\r\n"
                            f"Content-Type: application/json\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            f"\r\n{body}"
                        )
                    except Exception as _exc:
                        logger.exception("customer-telegram hook error")
                        body = _json.dumps({"error": str(_exc)})
                        resp = (
                            f"HTTP/1.0 500 Internal Server Error\r\n"
                            f"Content-Type: application/json\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            f"\r\n{body}"
                        )
            elif method == "POST" and path == "/hooks/foolish-storefront-review":
                import os as _os
                _hdr_end = data.find(b"\r\n\r\n")
                body_bytes = data[_hdr_end + 4:] if _hdr_end != -1 else b""
                _sf_secret = _os.environ.get("FOOLISH_STOREFRONT_WH_SECRET", "")
                _sf_sig = _parse_http_headers(data).get("x-foolish-signature", "")
                if not _verify_hmac(body_bytes, _sf_sig, _sf_secret):
                    logger.warning("foolish-storefront-review: invalid signature from {}", peer_ip)
                    _body401 = _json.dumps({"error": "Unauthorized"})
                    writer.write(
                        f"HTTP/1.0 401 Unauthorized\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(_body401)}\r\n\r\n{_body401}".encode()
                    )
                    await writer.drain()
                    writer.close()
                    return
                try:
                    review = _json.loads(body_bytes.decode("utf-8", errors="replace"))

                    telegram_cfg = config.channels.telegram
                    tg_allow = (telegram_cfg.get("allowFrom") or []) if isinstance(telegram_cfg, dict) else (getattr(telegram_cfg, "allow_from", None) or [])
                    chat_id = str(tg_allow[0]) if tg_allow else ""

                    if chat_id:
                        rating = int(review.get("rating", 0))
                        stars = "⭐" * rating
                        reviewer = review.get("reviewerName", "Anonimo")
                        product_name = review.get("productName", review.get("productSlug", "?"))
                        body_text = review.get("body") or ""
                        photo_urls = review.get("photoUrls", [])
                        publish_url = review.get("publishUrl", "")
                        remove_url = review.get("removeUrl", "")

                        if len(photo_urls) == 1:
                            photo_note = "\n📸 1 foto allegata"
                        elif len(photo_urls) > 1:
                            photo_note = f"\n📸 {len(photo_urls)} foto allegate"
                        else:
                            photo_note = ""

                        msg_text = (
                            f"{stars} — {reviewer}\n"
                            f"Prodotto: {product_name}"
                            f"{photo_note}\n\n"
                            f'"{body_text}"\n\n'
                            f"→ Pubblica: {publish_url}\n"
                            f"→ Rimuovi: {remove_url}"
                        )

                        asyncio.create_task(_deliver_to_channel(
                            OutboundMessage(channel="telegram", chat_id=chat_id, content=msg_text),
                        ))
                        logger.info("foolish-storefront-review hook: notified telegram {}", chat_id)

                    body = _json.dumps({"ok": True})
                    resp = (
                        f"HTTP/1.0 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
                except Exception as _exc:
                    logger.exception("foolish-storefront-review hook error")
                    body = _json.dumps({"error": str(_exc)})
                    resp = (
                        f"HTTP/1.0 500 Internal Server Error\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
            elif method == "POST" and path == "/hooks/foolish-storefront-cron":
                import os as _os
                _hdr_end = data.find(b"\r\n\r\n")
                body_bytes = data[_hdr_end + 4:] if _hdr_end != -1 else b""
                _sf_secret = _os.environ.get("FOOLISH_STOREFRONT_WH_SECRET", "")
                _sf_sig = _parse_http_headers(data).get("x-foolish-signature", "")
                if not _verify_hmac(body_bytes, _sf_sig, _sf_secret):
                    logger.warning("foolish-storefront-cron: invalid signature from {}", peer_ip)
                    _body401 = _json.dumps({"error": "Unauthorized"})
                    writer.write(
                        f"HTTP/1.0 401 Unauthorized\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(_body401)}\r\n\r\n{_body401}".encode()
                    )
                    await writer.drain()
                    writer.close()
                    return
                try:
                    cron = _json.loads(body_bytes.decode("utf-8", errors="replace"))

                    cron_name = cron.get("cron", "unknown")
                    sent = int(cron.get("sent", 0))
                    recipients = cron.get("recipients", [])
                    errors = cron.get("errors", [])

                    _cron_descriptions = {
                        "abandoned_cart": "Email carrello abbandonato — clienti che hanno iniziato il checkout ma non hanno completato l'acquisto (attesa >1h)",
                        "review_request": "Email richiesta recensione — clienti con ordine consegnato da >7 giorni senza recensione",
                        "reengagement": "Email riattivazione — clienti attivi senza acquisti da >90 giorni e nessuna email negli ultimi 30",
                    }

                    telegram_cfg = config.channels.telegram
                    tg_allow = (telegram_cfg.get("allowFrom") or []) if isinstance(telegram_cfg, dict) else (getattr(telegram_cfg, "allow_from", None) or [])
                    chat_id = str(tg_allow[0]) if tg_allow else ""

                    if chat_id:
                        icon = "⚠️" if errors else "✅"
                        description = _cron_descriptions.get(cron_name, cron_name)
                        msg_text = f"{icon} {description}\nInviate: {sent}"
                        if recipients:
                            recipient_lines = "\n".join(f"  • {r}" for r in recipients[:10])
                            msg_text += f"\nDestinatari:\n{recipient_lines}"
                            if len(recipients) > 10:
                                msg_text += f"\n  ... e altri {len(recipients) - 10}"
                        if errors:
                            error_lines = "\n".join(f"  • {e}" for e in errors[:5])
                            msg_text += f"\nErrori ({len(errors)}):\n{error_lines}"
                            if len(errors) > 5:
                                msg_text += f"\n  ... e altri {len(errors) - 5}"
                        asyncio.create_task(_deliver_to_channel(
                            OutboundMessage(channel="telegram", chat_id=chat_id, content=msg_text),
                        ))
                        logger.info("foolish-storefront-cron hook: {} sent={} errors={}", cron_name, sent, len(errors))

                    body = _json.dumps({"ok": True})
                    resp = (
                        f"HTTP/1.0 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
                except Exception as _exc:
                    logger.exception("foolish-storefront-cron hook error")
                    body = _json.dumps({"error": str(_exc)})
                    resp = (
                        f"HTTP/1.0 500 Internal Server Error\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
            elif method == "POST" and path == "/hooks/foolish-push-subscribed":
                import os as _os
                _hdr_end = data.find(b"\r\n\r\n")
                body_bytes = data[_hdr_end + 4:] if _hdr_end != -1 else b""
                _sf_secret = _os.environ.get("FOOLISH_STOREFRONT_WH_SECRET", "")
                _sf_sig = _parse_http_headers(data).get("x-foolish-signature", "")
                if not _verify_hmac(body_bytes, _sf_sig, _sf_secret):
                    logger.warning("foolish-push-subscribed: invalid signature from {}", peer_ip)
                    _body401 = _json.dumps({"error": "Unauthorized"})
                    writer.write(
                        f"HTTP/1.0 401 Unauthorized\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(_body401)}\r\n\r\n{_body401}".encode()
                    )
                    await writer.drain()
                    writer.close()
                    return
                try:
                    payload = _json.loads(body_bytes.decode("utf-8", errors="replace"))
                    email = payload.get("email", "sconosciuto")

                    telegram_cfg = config.channels.telegram
                    tg_allow = (telegram_cfg.get("allowFrom") or []) if isinstance(telegram_cfg, dict) else (getattr(telegram_cfg, "allow_from", None) or [])
                    chat_id = str(tg_allow[0]) if tg_allow else ""

                    if chat_id:
                        msg_text = (
                            f"🔔 Nuovo cliente ha attivato le notifiche push!\n"
                            f"Email: {email}\n\n"
                            f"Ho inviato il welcome push automatico."
                        )
                        asyncio.create_task(_deliver_to_channel(
                            OutboundMessage(channel="telegram", chat_id=chat_id, content=msg_text),
                        ))
                        logger.info("foolish-push-subscribed hook: notified telegram for {}", email)

                    body = _json.dumps({"ok": True})
                    resp = (
                        f"HTTP/1.0 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
                except Exception as _exc:
                    logger.exception("foolish-push-subscribed hook error")
                    body = _json.dumps({"error": str(_exc)})
                    resp = (
                        f"HTTP/1.0 500 Internal Server Error\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
            elif method == "POST" and path == "/hooks/zernio-event":
                import os as _os
                _hdr_end = data.find(b"\r\n\r\n")
                body_bytes = data[_hdr_end + 4:] if _hdr_end != -1 else b""
                _zernio_secret = _os.environ.get("ZERNIO_WEBHOOK_SECRET", "")
                _zh = _parse_http_headers(data)
                # Log all headers so we can learn Zernio's signing scheme
                _sig_headers = {k: v for k, v in _zh.items() if any(
                    kw in k for kw in ("auth", "sign", "token", "secret", "key", "zernio", "hub")
                )}
                logger.info("zernio-event: incoming headers (sig-related): {}", _sig_headers)
                _zernio_sig = (
                    _zh.get("x-zernio-signature", "")
                    or _zh.get("x-hub-signature-256", "")
                    or _zh.get("x-hub-signature", "")
                    or _zh.get("authorization", "").removeprefix("Bearer ").strip()
                    or _zh.get("x-webhook-secret", "")
                    or _zh.get("x-secret", "")
                )
                # Plain-token fallback: if secret matches directly (some platforms send raw token)
                _plain_match = _zernio_secret and (_zernio_sig == _zernio_secret)
                if not _plain_match and not _verify_hmac(body_bytes, _zernio_sig, _zernio_secret):
                    logger.warning("zernio-event: auth failed from {} — headers: {}", peer_ip, _sig_headers)
                    _body401 = _json.dumps({"error": "Unauthorized"})
                    writer.write(
                        f"HTTP/1.0 401 Unauthorized\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(_body401)}\r\n\r\n{_body401}".encode()
                    )
                    await writer.drain()
                    writer.close()
                    return
                try:
                    evt = _json.loads(body_bytes.decode("utf-8", errors="replace"))

                    event_type = evt.get("event") or evt.get("type") or "unknown"
                    post_id = evt.get("postId") or evt.get("post_id", "")
                    account_id = evt.get("accountId") or evt.get("account_id", "")

                    telegram_cfg = config.channels.telegram
                    tg_allow = (telegram_cfg.get("allowFrom") or []) if isinstance(telegram_cfg, dict) else (getattr(telegram_cfg, "allow_from", None) or [])
                    chat_id = str(tg_allow[0]) if tg_allow else ""

                    # Scribble log
                    _scribble_dir = _pathlib.Path("/home/ab/.nanobot/memory/scribble")
                    _scribble_dir.mkdir(parents=True, exist_ok=True)
                    _today = _datetime.datetime.now().strftime("%Y-%m-%d")
                    _scribble_path = _scribble_dir / f"zernio-{_today}.md"
                    try:
                        with open(_scribble_path, "a") as _f:
                            _f.write(
                                f"- [{_datetime.datetime.now().strftime('%H:%M')}] {event_type}"
                                f" postId={post_id or 'N/A'} accountId={account_id or 'N/A'}\n"
                            )
                    except Exception:
                        pass

                    def _schedule_frank_zernio(_name: str, _msg: str, _delay_s: int = 2) -> None:
                        from nanobot.cron.types import CronSchedule as _CS
                        import time as _t
                        cron.add_job(
                            name=_name,
                            schedule=_CS(kind="at", at_ms=int(_t.time() * 1000) + _delay_s * 1000),
                            message=_msg,
                            deliver=True,
                            channel="telegram",
                            to=chat_id,
                            channel_meta={
                                "user_id": int(chat_id) if chat_id.isdigit() else 0,
                                "username": "ale_boss_live",
                                "first_name": "Alessandro",
                                "is_group": False,
                                "message_thread_id": None,
                                "is_forum": False,
                                "reply_to_message_id": None,
                                "_wants_stream": False,
                            },
                            session_key=f"telegram:{chat_id}",
                            delete_after_run=True,
                        )

                    # ---- post.published ----
                    if event_type in ("post.published", "post_published"):
                        _platform = evt.get("platform", "instagram")
                        _caption = (evt.get("content") or evt.get("caption") or "")[:80]
                        _published_at = evt.get("publishedAt") or evt.get("published_at", "")
                        if chat_id:
                            asyncio.create_task(_deliver_to_channel(
                                OutboundMessage(
                                    channel="telegram",
                                    chat_id=chat_id,
                                    content=(
                                        f"✅ Post pubblicato su {_platform}\n"
                                        f"ID: {post_id}\n"
                                        f"Account: {account_id}\n"
                                        f"Ora: {_published_at}\n"
                                        + (f'"{_caption}…"' if _caption else "")
                                    ),
                                )
                            ))
                        logger.info("zernio-event: post.published postId={} account={}", post_id, account_id)

                    # ---- post.failed ----
                    elif event_type in ("post.failed", "post_failed"):
                        _error = evt.get("error") or evt.get("errorMessage") or "errore sconosciuto"
                        _platform = evt.get("platform", "instagram")
                        if chat_id:
                            asyncio.create_task(_deliver_to_channel(
                                OutboundMessage(
                                    channel="telegram",
                                    chat_id=chat_id,
                                    content=(
                                        f"🚨 Post FALLITO su {_platform}\n"
                                        f"ID: {post_id}\n"
                                        f"Account: {account_id}\n"
                                        f"Errore: {_error[:300]}"
                                    ),
                                )
                            ))
                        if chat_id:
                            _schedule_frank_zernio(
                                f"zernio-post-failed-{post_id}",
                                (
                                    f"Il post Zernio {post_id} (account {account_id}) ha fallito la pubblicazione su {_platform}.\n"
                                    f"Errore: {_error}\n\n"
                                    f"Usa `posts_get` per recuperare il post, poi `posts_retry` per ritentare la pubblicazione "
                                    f"oppure `posts_create` per ricrearlo se non recuperabile.\n"
                                    f"Se il problema persiste, notifica Alessandro con i dettagli tecnici."
                                ),
                            )
                        logger.warning("zernio-event: post.failed postId={} error={}", post_id, _error)

                    # ---- message.received (DM inbound) ----
                    elif event_type in ("message.received", "message_received", "dm.received", "dm_received"):
                        _sender = (
                            evt.get("from") or evt.get("sender") or {}
                        )
                        _sender_name = (
                            _sender.get("name") or _sender.get("username") or
                            evt.get("fromUsername") or evt.get("senderUsername") or "utente"
                        )
                        _sender_username = (
                            _sender.get("username") or
                            evt.get("fromUsername") or evt.get("senderUsername") or ""
                        )
                        _text = evt.get("text") or evt.get("message") or ""
                        _conversation_id = evt.get("conversationId") or evt.get("conversation_id") or ""
                        if chat_id:
                            _schedule_frank_zernio(
                                f"zernio-dm-{_conversation_id or _sender_username}",
                                (
                                    f"Hai ricevuto un DM su Instagram (Zernio) da @{_sender_username} ({_sender_name}).\n"
                                    f"Account: {account_id}\n"
                                    f"Conversation ID: {_conversation_id}\n"
                                    f"Messaggio: \"{_text}\"\n\n"
                                    f"Valuta se rispondere. Se sì, usa il tool Zernio MCP per inviare la risposta "
                                    f"nella conversazione {_conversation_id}. "
                                    f"Applica la voce Foolish Butcher (informale, diretto, utile). "
                                    f"Se la richiesta richiede intervento umano (resi, problemi complessi), "
                                    f"notifica Alessandro con il testo del DM."
                                ),
                            )
                        logger.info("zernio-event: dm received from={} conversation={}", _sender_username, _conversation_id)

                    # ---- comment.received ----
                    elif event_type in ("comment.received", "comment_received"):
                        _author = evt.get("authorUsername") or evt.get("author") or "utente"
                        _comment_text = evt.get("text") or evt.get("comment") or ""
                        _comment_id = evt.get("commentId") or evt.get("comment_id") or ""
                        # Keywords standard da frank-ig-playbook.md §3
                        _keywords = {"PELLE", "SEBO", "ROTOLO"}
                        _has_keyword = any(kw in (_comment_text or "").upper() for kw in _keywords)
                        if chat_id:
                            _schedule_frank_zernio(
                                f"zernio-comment-{_comment_id or _author}",
                                (
                                    f"Nuovo commento Instagram (Zernio) su post {post_id}.\n"
                                    f"Autore: @{_author}\n"
                                    f"Commento: \"{_comment_text}\"\n"
                                    f"Comment ID: {_comment_id}\n"
                                    f"Account: {account_id}\n"
                                    + (f"⚠️ Contiene keyword trigger ({', '.join(_keywords & set((_comment_text or '').upper().split()))}).\n" if _has_keyword else "")
                                    + "\n"
                                    f"Se il commento contiene una keyword (PELLE/SEBO/ROTOLO) e non c'è già un'automazione attiva per questo post, "
                                    f"usa `comment_automations_create_comment_automation` per creare il listener. "
                                    f"Se il commento è una domanda genuina senza keyword, valuta se rispondere con `comments_reply_to_inbox_post`. "
                                    f"Se è spam o irrilevante, ignora."
                                ),
                            )
                        logger.info("zernio-event: comment received postId={} author={} keyword={}", post_id, _author, _has_keyword)

                    # ---- analytics.ready / post.analytics ----
                    elif event_type in ("analytics.ready", "analytics_ready", "post.analytics", "post_analytics"):
                        _reach = evt.get("reach") or evt.get("impressions") or 0
                        _engagement = evt.get("engagement") or evt.get("engagementRate") or 0
                        _saves = evt.get("saves") or 0
                        _shares = evt.get("shares") or 0
                        if chat_id:
                            _schedule_frank_zernio(
                                f"zernio-analytics-{post_id}",
                                (
                                    f"Analytics disponibili per il post Zernio {post_id} (account {account_id}).\n"
                                    f"Dati ricevuti: reach={_reach}, engagement={_engagement}, saves={_saves}, shares={_shares}\n\n"
                                    f"Fai una valutazione rapida del post: ha performato bene rispetto agli altri? "
                                    f"Aggiorna il buffer dei format in `SEBO_LAUNCH_KIT.md` o nel tuo contesto se questo format "
                                    f"ha convertito bene. Usa `analytics_get_analytics` per avere il quadro completo se serve. "
                                    f"Notifica Alessandro solo se le performance sono eccezionalmente buone o cattive."
                                ),
                            )
                        logger.info("zernio-event: analytics.ready postId={} reach={}", post_id, _reach)

                    elif event_type in ("webhook.test", "webhook_test"):
                        logger.info("zernio-event: test webhook received OK — Zernio integration active")

                    else:
                        logger.info("zernio-event: unhandled event type '{}' — logged", event_type)

                    body = _json.dumps({"ok": True})
                    resp = (
                        f"HTTP/1.0 200 OK\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
                except Exception as _exc:
                    logger.exception("zernio-event hook error")
                    body = _json.dumps({"error": str(_exc)})
                    resp = (
                        f"HTTP/1.0 500 Internal Server Error\r\n"
                        f"Content-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"\r\n{body}"
                    )
            else:
                body = "Not Found"
                resp = (
                    f"HTTP/1.0 404 Not Found\r\n"
                    f"Content-Type: text/plain\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"\r\n{body}"
                )

            writer.write(resp.encode())
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, host, health_port)
        console.print(f"[green]✓[/green] Health endpoint: http://{host}:{health_port}/health")
        async with server:
            await server.serve_forever()
    # Register Dream system job (idempotent on restart)
    from nanobot.cron.types import CronJob, CronPayload, CronSchedule
    dream_cfg = config.agents.defaults.dream
    if dream_cfg.enabled:
        cron.register_system_job(CronJob(
            id="dream",
            name="dream",
            schedule=dream_cfg.build_schedule(config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        ))
        console.print(f"[green]✓[/green] Dream: {dream_cfg.describe_schedule()}")
    else:
        console.print("[yellow]○[/yellow] Dream: disabled")

    # Register Heartbeat system job (idempotent on restart)
    if hb_cfg.enabled:
        cron.register_system_job(CronJob(
            id="heartbeat",
            name="heartbeat",
            schedule=CronSchedule(
                kind="every",
                every_ms=hb_cfg.interval_s * 1000,
                tz=config.agents.defaults.timezone,
            ),
            payload=CronPayload(kind="system_event"),
        ))

    async def _open_browser_when_ready() -> None:
        """Wait for the gateway to bind, then point the user's browser at the webui."""
        if not open_browser_url:
            return
        import webbrowser
        # Channels start asynchronously; a short poll lets us avoid racing the bind.
        for _ in range(40):  # ~4s max
            try:
                reader, writer = await asyncio.open_connection(
                    config.gateway.host or "127.0.0.1", port
                )
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.1)
        try:
            webbrowser.open(open_browser_url)
            console.print(f"[green]✓[/green] Opened browser at {open_browser_url}")
        except Exception as e:
            console.print(f"[yellow]Could not open browser ({e}); visit {open_browser_url}[/yellow]")

    async def run():
        tasks: list[asyncio.Task] = []
        shutdown_task: asyncio.Task | None = None
        runtime_tasks: asyncio.Future | None = None
        runtime_tasks_drained = False
        shutdown_event = asyncio.Event()
        _ensure_gateway_tty_signal_mode()
        restore_shutdown_handlers = _install_gateway_shutdown_handlers(
            asyncio.get_running_loop(),
            shutdown_event,
            tasks,
            console.print,
        )
        try:
            await cron.start()
            tasks = [
                asyncio.create_task(agent.run(), name="nanobot-agent-loop"),
                asyncio.create_task(channels.start_all(), name="nanobot-channels"),
            ]
            if health_server_enabled:
                tasks.append(asyncio.create_task(
                    _health_server(config.gateway.host, port),
                    name="nanobot-health-server",
                ))
            if open_browser_url:
                tasks.append(asyncio.create_task(
                    _open_browser_when_ready(),
                    name="nanobot-open-browser",
                ))
            runtime_tasks = asyncio.gather(*tasks)
            shutdown_task = asyncio.create_task(
                shutdown_event.wait(),
                name="nanobot-gateway-shutdown",
            )
            done, _pending = await asyncio.wait(
                {runtime_tasks, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if runtime_tasks in done:
                runtime_tasks_drained = True
                await runtime_tasks
            elif runtime_tasks is not None:
                runtime_tasks.cancel()
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback

            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
        finally:
            try:
                if shutdown_task and not shutdown_task.done():
                    shutdown_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await shutdown_task
                cron.stop()
                agent.stop()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if runtime_tasks is not None and not runtime_tasks_drained:
                    with suppress(asyncio.CancelledError, Exception):
                        await runtime_tasks
                await channels.stop_all()
                # Flush all cached sessions to durable storage before exit.
                # This prevents data loss on filesystems with write-back
                # caching (rclone VFS, NFS, FUSE mounts, etc.).
                flushed = agent.sessions.flush_all()
                if flushed:
                    logger.info("Shutdown: flushed {} session(s) to disk", flushed)
            finally:
                restore_shutdown_handlers()

    asyncio.run(run())


app.add_typer(
    create_gateway_app(
        console=console,
        log_handler_id=_log_handler_id,
        load_runtime_config=_load_runtime_config,
        run_gateway=_run_gateway,
    ),
    name="gateway",
)


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"),
):
    """Interact with the agent directly."""
    from loguru import logger

    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.providers.image_generation import image_gen_provider_configs

    config = _load_runtime_config(config, workspace)
    sync_workspace_templates(config.workspace_path)

    bus = MessageBus()

    # Preserve existing single-workspace installs, but keep custom workspaces clean.
    if is_default_workspace(config.workspace_path):
        _migrate_cron_store(config)

    # Create cron service with workspace-scoped store
    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    try:
        agent_loop = AgentLoop.from_config(
            config, bus,
            cron_service=cron,
            image_generation_provider_configs=image_gen_provider_configs(config),
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc
    restart_notice = consume_restart_notice_from_env()
    if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
        _print_agent_response(
            format_restart_completed_message(restart_notice.started_at_raw),
            render_markdown=False,
        )

    # Shared reference for progress callbacks
    _thinking: ThinkingSpinner | None = None

    def _make_progress(renderer: StreamRenderer | None = None):
        reasoning_buffer = _ReasoningBuffer()

        async def _cli_progress(content: str, *, tool_hint: bool = False, reasoning: bool = False, **_kwargs: Any) -> None:
            ch = agent_loop.channels_config

            if _kwargs.get("reasoning_end"):
                if ch and not ch.show_reasoning:
                    reasoning_buffer.clear()
                else:
                    _flush_cli_reasoning(reasoning_buffer, _thinking, renderer)
                return

            if reasoning:
                if ch and not ch.show_reasoning:
                    reasoning_buffer.clear()
                    return
                text = reasoning_buffer.add(content)
                if text:
                    _print_cli_reasoning(text, _thinking, renderer)
                return
            if ch and tool_hint and not ch.send_tool_hints:
                return
            if ch and not tool_hint and not ch.send_progress:
                return
            _print_cli_progress_line(content, _thinking, renderer)
        return _cli_progress

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            renderer = StreamRenderer(
                render_markdown=markdown,
                bot_name=config.agents.defaults.bot_name,
                bot_icon=config.agents.defaults.bot_icon,
            )
            response = await agent_loop.process_direct(
                message, session_id,
                on_progress=_make_progress(renderer),
                on_stream=renderer.on_delta,
                on_stream_end=renderer.on_end,
            )
            if not renderer.streamed:
                await renderer.close()
                print_kwargs: dict[str, Any] = {}
                if renderer.header_printed:
                    print_kwargs["show_header"] = False
                _print_agent_response(
                    response.content if response else "",
                    render_markdown=markdown,
                    metadata=response.metadata if response else None,
                    **print_kwargs,
                )
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from nanobot.bus.events import InboundMessage
        _init_prompt_session()
        _model, _preset_tag = _model_display(config)
        _icon = config.agents.defaults.bot_icon or __logo__
        console.print(f"{_icon} Interactive mode [bold blue]({_model})[/bold blue]{_preset_tag} — type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n")

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            _restore_terminal()
            console.print(f"\nReceived {sig_name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP is not available on Windows
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, 'SIGPIPE'):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive():
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[tuple[str, dict]] = []
            renderer: StreamRenderer | None = None
            reasoning_buffer = _ReasoningBuffer()

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

                        if msg.metadata.get("_stream_delta"):
                            if renderer:
                                await renderer.on_delta(msg.content)
                            continue
                        if msg.metadata.get("_stream_end"):
                            if renderer:
                                await renderer.on_end(
                                    resuming=msg.metadata.get("_resuming", False),
                                )
                            continue
                        if msg.metadata.get("_streamed"):
                            turn_done.set()
                            continue

                        if await _maybe_print_interactive_progress(
                            msg,
                            renderer,
                            agent_loop.channels_config,
                            renderer,
                            reasoning_buffer,
                        ):
                            continue

                        if not turn_done.is_set():
                            if msg.content:
                                turn_response.append((msg.content, dict(msg.metadata or {})))
                            turn_done.set()
                        elif msg.content:
                            await _print_interactive_response(
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
                        _flush_pending_tty_input()
                        # Stop spinner before user input to avoid prompt_toolkit conflicts
                        if renderer:
                            renderer.stop_for_input()
                        user_input = _sanitize_surrogates(await _read_interactive_input_async())
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        turn_done.clear()
                        turn_response.clear()
                        reasoning_buffer.clear()
                        renderer = StreamRenderer(
                            render_markdown=markdown,
                            bot_name=config.agents.defaults.bot_name,
                            bot_icon=config.agents.defaults.bot_icon,
                        )

                        await bus.publish_inbound(InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                            metadata={"_wants_stream": True},
                        ))

                        await turn_done.wait()

                        if turn_response:
                            content, meta = turn_response[0]
                            if content and not meta.get("_streamed"):
                                if renderer:
                                    await renderer.close()
                                print_kwargs: dict[str, Any] = {}
                                if renderer and renderer.header_printed:
                                    print_kwargs["show_header"] = False
                                _print_agent_response(
                                    content,
                                    render_markdown=markdown,
                                    metadata=meta,
                                    **print_kwargs,
                                )
                        elif renderer and not renderer.streamed:
                            await renderer.close()
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

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status(
    config_path: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Show channel status."""
    from nanobot.channels.registry import discover_all
    from nanobot.config.loader import load_config, set_config_path

    resolved_config_path = Path(config_path).expanduser().resolve() if config_path else None
    if resolved_config_path is not None:
        set_config_path(resolved_config_path)

    config = load_config(resolved_config_path)

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled")

    for name, cls in sorted(discover_all().items()):
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            "[green]\u2713[/green]" if enabled else "[dim]\u2717[/dim]",
        )

    console.print(table)


@channels_app.command("login")
def channels_login(
    channel_name: str = typer.Argument(..., help="Channel name (e.g. weixin, whatsapp)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-authentication even if already logged in"),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Authenticate with a channel via QR code or other interactive login."""
    from nanobot.channels.registry import discover_all
    from nanobot.config.loader import load_config, set_config_path

    resolved_config_path = Path(config_path).expanduser().resolve() if config_path else None
    if resolved_config_path is not None:
        set_config_path(resolved_config_path)

    config = load_config(resolved_config_path)
    channel_cfg = getattr(config.channels, channel_name, None) or {}

    # Validate channel exists
    all_channels = discover_all()
    if channel_name not in all_channels:
        available = ", ".join(all_channels.keys())
        console.print(f"[red]Unknown channel: {channel_name}[/red]  Available: {available}")
        raise typer.Exit(1)

    console.print(f"{__logo__} {all_channels[channel_name].display_name} Login\n")

    channel_cls = all_channels[channel_name]
    channel = channel_cls(channel_cfg, bus=None)

    success = asyncio.run(channel.login(force=force))

    if not success:
        raise typer.Exit(1)


# ============================================================================
# Plugin Commands
# ============================================================================

plugins_app = typer.Typer(help="Manage channel plugins")
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def plugins_list():
    """List all discovered channels (built-in and plugins)."""
    from nanobot.channels.registry import discover_all, discover_channel_names
    from nanobot.config.loader import load_config

    config = load_config()
    builtin_names = set(discover_channel_names())
    all_channels = discover_all()

    table = Table(title="Channel Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Enabled")

    for name in sorted(all_channels):
        cls = all_channels[name]
        source = "builtin" if name in builtin_names else "plugin"
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            source,
            "[green]yes[/green]" if enabled else "[dim]no[/dim]",
        )

    console.print(table)


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        _model, _preset_tag = _model_display(config)
        console.print(f"Model: {_model}{_preset_tag}")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, Callable[[], None]] = {}
_LOGOUT_HANDLERS: dict[str, Callable[[], None]] = {}

_PROVIDER_DISPLAY: dict[str, str] = {
    "openai_codex": "OpenAI Codex",
    "github_copilot": "GitHub Copilot",
}


def _register_login(name: str):
    """Register an OAuth login handler."""
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn
        return fn

    return decorator


def _register_logout(name: str):
    """Register an OAuth logout handler."""
    def decorator(fn):
        _LOGOUT_HANDLERS[name] = fn
        return fn
    return decorator


def _resolve_oauth_provider(provider: str):
    """Resolve and validate an OAuth provider configuration."""
    from nanobot.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)
    return spec


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """Authenticate with an OAuth provider."""
    spec = _resolve_oauth_provider(provider)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@provider_app.command("logout")
def provider_logout(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """Log out from an OAuth provider."""
    spec = _resolve_oauth_provider(provider)

    handler = _LOGOUT_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Logout not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Logout - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive

        token = None
        with suppress(Exception):
            token = get_token()
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]")
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_logout("openai_codex")
def _logout_openai_codex() -> None:
    """Clear local OAuth credentials for OpenAI Codex."""
    try:
        from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
        from oauth_cli_kit.storage import FileTokenStorage
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)

    storage = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename)
    _delete_oauth_files(storage.get_token_path(), _PROVIDER_DISPLAY["openai_codex"])


@_register_logout("github_copilot")
def _logout_github_copilot() -> None:
    """Clear local OAuth credentials for GitHub Copilot."""
    try:
        from nanobot.providers.github_copilot_provider import get_storage
    except ImportError:
        console.print("[red]GitHub Copilot provider unavailable. Ensure oauth-cli-kit is installed.[/red]")
        raise typer.Exit(1)

    storage = get_storage()
    _delete_oauth_files(storage.get_token_path(), _PROVIDER_DISPLAY["github_copilot"])


def _delete_oauth_files(token_path: Path, provider_label: str) -> None:
    """Delete OAuth token and lock files, reporting the result."""
    removed_paths: list[Path] = []
    skipped: list[tuple[Path, OSError]] = []
    for path in (token_path, token_path.with_suffix(".lock")):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            skipped.append((path, exc))
            continue
        removed_paths.append(path)

    if not removed_paths and not skipped:
        console.print(f"[yellow]! No local OAuth credentials found for {provider_label}[/yellow]")
        return

    if removed_paths:
        console.print(f"[green]✓ Logged out from {provider_label}[/green]")
        for path in removed_paths:
            console.print(f"[dim]Removed: {path}[/dim]")
    for path, exc in skipped:
        console.print(f"[yellow]! Could not remove {path}: {exc}[/yellow]")


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    try:
        from nanobot.providers.github_copilot_provider import login_github_copilot

        console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")
        token = login_github_copilot(
            print_fn=lambda s: console.print(s),
            prompt_fn=lambda s: typer.prompt(s),
        )
        account = token.account_id or "GitHub"
        console.print(f"[green]✓ Authenticated with GitHub Copilot[/green]  [dim]{account}[/dim]")
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
