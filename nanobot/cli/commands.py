"""CLI commands for nanobot."""

import asyncio
import datetime as _datetime
import os
import pathlib as _pathlib
import select
import signal
import sys
from collections.abc import Callable
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


def _sanitize_surrogates(text: str) -> str:
    """Reconstruct surrogate pairs into real characters; replace lone surrogates.

    On Windows, console input may produce lone surrogate code points (e.g.
    ``\\ud83d\\udc08`` for U+1F408).  Round-tripping through UTF-16 reconstructs
    paired surrogates into their actual characters and replaces unpaired ones
    with U+FFFD.
    """
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")


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


@app.command()
def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the nanobot gateway."""
    if verbose:
        logger.remove(_log_handler_id)
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <5}</level> | "
                "<cyan>{extra[channel]}</cyan> | "
                "<level>{message}</level>"
            ),
            level="DEBUG",
            colorize=None,
            filter=lambda record: record["extra"].setdefault("channel", "-") or True,
        )
    cfg = _load_runtime_config(config, workspace)
    _run_gateway(cfg, port=port)


def _load_or_create_desktop_config(config: str | None, workspace: str | None) -> Config:
    """Load the desktop-owned config, creating it on first launch."""
    from nanobot.config.loader import (
        get_config_path,
        load_config,
        resolve_config_env_vars,
        save_config,
        set_config_path,
    )
    from nanobot.config.schema import Config as NanobotConfig

    config_path = Path(config).expanduser().resolve() if config else get_config_path()
    set_config_path(config_path)
    created = False
    if config_path.exists():
        try:
            loaded = resolve_config_env_vars(load_config(config_path))
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)
    else:
        loaded = NanobotConfig()
        created = True

    if workspace:
        workspace_path = Path(workspace).expanduser()
        loaded.agents.defaults.workspace = str(workspace_path)
        created = True

    if created:
        save_config(loaded, config_path)
    return loaded


def _configure_desktop_gateway(
    config: Config,
    *,
    webui_port: int,
    webui_socket: str | None,
    token_issue_secret: str,
) -> None:
    """Force a local WebSocket-only gateway for the desktop app process."""
    config.gateway.host = "127.0.0.1"
    config.gateway.port = webui_port
    config.gateway.heartbeat.enabled = False

    extras = dict(getattr(config.channels, "__pydantic_extra__", None) or {})
    for name, section in list(extras.items()):
        if name == "websocket":
            continue
        if isinstance(section, dict):
            extras[name] = {**section, "enabled": False}
        else:
            with suppress(Exception):
                setattr(section, "enabled", False)
            extras[name] = section

    websocket_cfg = extras.get("websocket")
    if not isinstance(websocket_cfg, dict):
        websocket_cfg = {}
    websocket_cfg.update(
        {
            "enabled": True,
            "host": "127.0.0.1",
            "port": webui_port,
            "unix_socket_path": webui_socket or "",
            "path": "/",
            "token_issue_secret": token_issue_secret,
            "websocket_requires_token": True,
            "allow_from": ["*"],
            "streaming": True,
        }
    )
    extras["websocket"] = websocket_cfg
    config.channels.__pydantic_extra__ = extras


@app.command("desktop-gateway", hidden=True)
def desktop_gateway(
    webui_port: int = typer.Option(0, "--webui-port", min=0, max=65535),
    webui_socket: str | None = typer.Option(None, "--webui-socket", help="Unix socket path for desktop IPC"),
    token_issue_secret: str = typer.Option(..., "--token-issue-secret"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Desktop workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Desktop config file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the private local gateway used by nanobot Desktop."""
    if not token_issue_secret.strip():
        console.print("[red]Error: --token-issue-secret is required[/red]")
        raise typer.Exit(1)
    if webui_port <= 0 and not (webui_socket or "").strip():
        console.print("[red]Error: --webui-port or --webui-socket is required[/red]")
        raise typer.Exit(1)
    if verbose:
        logger.remove(_log_handler_id)
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <5}</level> | "
                "<cyan>{extra[channel]}</cyan> | "
                "<level>{message}</level>"
            ),
            level="DEBUG",
            colorize=None,
            filter=lambda record: record["extra"].setdefault("channel", "-") or True,
        )
    cfg = _load_or_create_desktop_config(config, workspace)
    _configure_desktop_gateway(
        cfg,
        webui_port=webui_port,
        webui_socket=webui_socket,
        token_issue_secret=token_issue_secret,
    )
    _run_gateway(
        cfg,
        port=webui_port,
        webui_static_dist=False,
        webui_runtime_surface="native",
        webui_runtime_capabilities={
            "can_restart_engine": True,
            "can_pick_folder": True,
            "can_open_logs": True,
            "can_export_diagnostics": True,
        },
        health_server_enabled=False,
    )


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
    from nanobot.agent.tools.cron import CronTool
    from nanobot.agent.tools.message import MessageTool
    from nanobot.bus.queue import MessageBus
    from nanobot.bus.runtime_events import RuntimeEventBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.providers.factory import build_provider_snapshot, load_provider_snapshot
    from nanobot.providers.image_generation import image_gen_provider_configs
    from nanobot.session.manager import SessionManager
    from nanobot.session.webui_turns import WebuiTurnCoordinator

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
    )
    WebuiTurnCoordinator(
        bus=bus,
        sessions=session_manager,
        schedule_background=lambda coro: agent._schedule_background(coro),
    ).subscribe(runtime_events)

    from nanobot.agent.loop import UNIFIED_SESSION_KEY
    from nanobot.bus.events import OutboundMessage

    def _channel_session_key(channel: str, chat_id: str) -> str:
        return (
            UNIFIED_SESSION_KEY
            if config.agents.defaults.unified_session
            else f"{channel}:{chat_id}"
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

        reminder_note = (
            "The scheduled time has arrived. Deliver this reminder to the user now, "
            "as a brief and natural message in their language. Speak directly to them — "
            "do not narrate progress, summarize, include user IDs, or add status reports "
            "like 'Done' or 'Reminded'.\n\n"
            f"Reminder: {job.payload.message}"
        )

        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)

        message_record_token = None
        if isinstance(message_tool, MessageTool):
            message_record_token = message_tool.set_record_channel_delivery(True)

        try:
            resp = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
                on_progress=_silent,
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)
            if isinstance(message_tool, MessageTool) and message_record_token is not None:
                message_tool.reset_record_channel_delivery(message_record_token)

        response = resp.content if resp else ""

        if job.payload.deliver and isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            should_notify = await evaluate_response(
                response, reminder_note, agent.provider, agent.model,
            )
            if should_notify:
                await _deliver_to_channel(
                    OutboundMessage(
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to,
                        content=response,
                        metadata=dict(job.payload.channel_meta),
                    ),
                    record=True,
                    session_key=job.payload.session_key,
                )
        return response

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
        webui_runtime_model_name=_webui_runtime_model_name,
        webui_static_dist=webui_static_dist,
        webui_runtime_surface=webui_runtime_surface,
        webui_runtime_capabilities=webui_runtime_capabilities,
    )

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        return "cli", "direct"

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
        text = message.get("text", "")
        customer_name = message["chat"].get("first_name", "")

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
        customer_context = (
            f"[canale: foolish_customer_bot | cliente: {customer_name} | chat_id: {chat_id}]\n"
            f"{text}"
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
            }, _f, ensure_ascii=False, indent=2)

        short_id = chat_id[-4:] if len(chat_id) >= 4 else chat_id
        if alessandros_chat:
            asyncio.create_task(_deliver_to_channel(
                OutboundMessage(
                    channel="telegram",
                    chat_id=alessandros_chat,
                    content=(
                        f"💬 Foolish Bot — {customer_name} (#{short_id})\n\n"
                        f"Messaggio:\n{text}\n\n"
                        f"💡 Proposta Frank:\n{proposed}\n\n"
                        f"Rispondi:\n"
                        f"• \"fb ok\" → invio la proposta\n"
                        f"• \"fb [testo]\" → invio il testo che scrivi\n"
                        f"• \"fb ignora\" → non rispondo"
                    ),
                )
            ))

    async def _health_server(host: str, health_port: int):
        """Lightweight HTTP health endpoint on the gateway port."""
        import json as _json

        async def handle(reader, writer):
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=5)
            except (asyncio.TimeoutError, ConnectionError):
                writer.close()
                return

            request_line = data.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
            method, path = "", ""
            parts = request_line.split(" ")
            if len(parts) >= 2:
                method, path = parts[0], parts[1]

            if method == "GET" and path == "/health":
                body = _json.dumps({"status": "ok"})
                resp = (
                    f"HTTP/1.0 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"\r\n{body}"
                )
            elif method == "POST" and path == "/hooks/foolish-storefront-order":
                try:
                    header_end = data.find(b"\r\n\r\n")
                    body_bytes = data[header_end + 4:] if header_end != -1 else b""
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
                try:
                    header_end = data.find(b"\r\n\r\n")
                    body_bytes = data[header_end + 4:] if header_end != -1 else b""
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
                try:
                    header_end = data.find(b"\r\n\r\n")
                    body_bytes = data[header_end + 4:] if header_end != -1 else b""
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
                try:
                    header_end = data.find(b"\r\n\r\n")
                    body_bytes = data[header_end + 4:] if header_end != -1 else b""
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
        try:
            await cron.start()
            tasks = [
                agent.run(),
                channels.start_all(),
            ]
            if health_server_enabled:
                tasks.append(_health_server(config.gateway.host, port))
            if open_browser_url:
                tasks.append(_open_browser_when_ready())
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback

            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
        finally:
            await agent.close_mcp()
            cron.stop()
            agent.stop()
            await channels.stop_all()
            # Flush all cached sessions to durable storage before exit.
            # This prevents data loss on filesystems with write-back
            # caching (rclone VFS, NFS, FUSE mounts, etc.).
            flushed = agent.sessions.flush_all()
            if flushed:
                logger.info("Shutdown: flushed {} session(s) to disk", flushed)

    asyncio.run(run())


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
        console.print(f"{__logo__} Interactive mode [bold blue]({_model})[/bold blue]{_preset_tag} — type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n")

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
