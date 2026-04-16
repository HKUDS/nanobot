"""CLI commands for nanobot."""

import asyncio
import hashlib
import os
import select
import signal
import subprocess
import sys
from contextlib import nullcontext, suppress
from pathlib import Path
from typing import Any

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from loguru import logger
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from nanobot import __logo__, __version__
from nanobot.cli.stream import StreamRenderer, ThinkingSpinner
from nanobot.config.paths import get_workspace_path, is_default_workspace
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates
from nanobot.utils.restart import (
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)


class SafeFileHistory(FileHistory):
    """FileHistory subclass that sanitizes surrogate characters on write.

    On Windows, special Unicode input (emoji, mixed-script) can produce
    surrogate characters that crash prompt_toolkit's file write.
    See issue #2846.
    """

    def store_string(self, string: str) -> None:
        safe = string.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
        super().store_string(safe)


app = typer.Typer(
    name="nanobot",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}


def _setup_gateway_logging(verbose: bool) -> None:
    """Configure loguru sinks for gateway runtime visibility."""
    configured_level = (os.environ.get("NANOBOT_LOG_LEVEL") or "").strip().upper()
    console_level = configured_level or ("DEBUG" if verbose else "INFO")

    logger.remove()
    logger.add(
        sys.stderr,
        level=console_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )

    logs_dir = Path.home() / ".nanobot" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(logs_dir / "gateway.log"),
        level="DEBUG",
        encoding="utf-8",
        rotation="10 MB",
        retention=5,
        enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )


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

    try:
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

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
        force_terminal=True,
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
) -> None:
    """Render assistant response with consistent terminal styling."""
    console = _make_console()
    content = response or ""
    body = _response_renderable(content, render_markdown, metadata)
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
        ansi = _render_interactive_ansi(lambda c: c.print(f"  [dim]↳ {text}[/dim]"))
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


def _print_cli_progress_line(text: str, thinking: ThinkingSpinner | None) -> None:
    """Print a CLI progress line, pausing the spinner if needed."""
    with thinking.pause() if thinking else nullcontext():
        console.print(f"  [dim]↳ {text}[/dim]")


async def _print_interactive_progress_line(text: str, thinking: ThinkingSpinner | None) -> None:
    """Print an interactive progress line, pausing the spinner if needed."""
    with thinking.pause() if thinking else nullcontext():
        await _print_interactive_line(text)


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
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
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


def _make_provider(config: Config):
    """Create the appropriate LLM provider from config.

    Routing is driven by ``ProviderSpec.backend`` in the registry.
    """
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.registry import find_by_name

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    # --- validation ---
    if backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            console.print("[red]Error: Azure OpenAI requires api_key and api_base.[/red]")
            console.print("Set them in ~/.nanobot/config.json under providers.azure_openai section")
            console.print("Use the model field to specify the deployment name.")
            raise typer.Exit(1)
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            console.print("[red]Error: No API key configured.[/red]")
            console.print("Set one in ~/.nanobot/config.json under providers section")
            raise typer.Exit(1)

    # --- instantiation by backend ---
    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    elif backend == "github_copilot":
        from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

        provider = GitHubCopilotProvider(default_model=model)
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider


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
    timeout: float | None = typer.Option(
        None, "--timeout", "-t", help="Per-request timeout (seconds)"
    ),
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

    from nanobot.agent.loop import AgentLoop
    from nanobot.api.server import create_app
    from nanobot.bus.queue import MessageBus
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
    provider = _make_provider(runtime_config)
    session_manager = SessionManager(runtime_config.workspace_path)
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=runtime_config.workspace_path,
        model=runtime_config.agents.defaults.model,
        max_iterations=runtime_config.agents.defaults.max_tool_iterations,
        context_window_tokens=runtime_config.agents.defaults.context_window_tokens,
        context_block_limit=runtime_config.agents.defaults.context_block_limit,
        max_tool_result_chars=runtime_config.agents.defaults.max_tool_result_chars,
        provider_retry_mode=runtime_config.agents.defaults.provider_retry_mode,
        web_config=runtime_config.tools.web,
        exec_config=runtime_config.tools.exec,
        restrict_to_workspace=runtime_config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=runtime_config.tools.mcp_servers,
        channels_config=runtime_config.channels,
        timezone=runtime_config.agents.defaults.timezone,
        unified_session=runtime_config.agents.defaults.unified_session,
        disabled_skills=runtime_config.agents.defaults.disabled_skills,
        session_ttl_minutes=runtime_config.agents.defaults.session_ttl_minutes,
    )

    model_name = runtime_config.agents.defaults.model
    console.print(f"{__logo__} Starting OpenAI-compatible API server")
    console.print(f"  [cyan]Endpoint[/cyan] : http://{host}:{port}/v1/chat/completions")
    console.print(f"  [cyan]Model[/cyan]    : {model_name}")
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
async def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the nanobot gateway."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob, CronSchedule
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.services.kosmos_tasks import KosmosTasksClient
    from nanobot.session.manager import SessionManager

    _setup_gateway_logging(verbose)
    logger.info(
        "Gateway starting (verbose={}, log_level={})",
        verbose,
        (os.environ.get("NANOBOT_LOG_LEVEL") or ("DEBUG" if verbose else "INFO")).upper(),
    )

    config = _load_runtime_config(config, workspace)
    port = port if port is not None else config.gateway.port

    console.print(f"{__logo__} Starting nanobot gateway version {__version__} on port {port}...")
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Preserve existing single-workspace installs, but keep custom workspaces clean.
    if is_default_workspace(config.workspace_path):
        _migrate_cron_store(config)

    # Create cron service with workspace-scoped store
    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_config=config.tools.web,
        context_block_limit=config.agents.defaults.context_block_limit,
        max_tool_result_chars=config.agents.defaults.max_tool_result_chars,
        provider_retry_mode=config.agents.defaults.provider_retry_mode,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
        unified_session=config.agents.defaults.unified_session,
        disabled_skills=config.agents.defaults.disabled_skills,
        session_ttl_minutes=config.agents.defaults.session_ttl_minutes,
    )

    # Register Kosmos agent hook for real-time events
    from nanobot.agent.hooks import create_kosmos_hook

    kosmos_hook = create_kosmos_hook(workspace=config.workspace_path)
    extra_hooks = getattr(agent, "_extra_hooks", None)
    if isinstance(extra_hooks, list):
        extra_hooks.append(kosmos_hook)

    kosmos_api_url = str(config.gateway.kosmos_api_url or "http://127.0.0.1:18794").strip()
    kosmos_tasks = KosmosTasksClient(base_url=kosmos_api_url)
    nanocats_task_lock = asyncio.Lock()
    active_subagent_roles: set[str] = set()
    subagents = getattr(agent, "subagents", None)
    dev_subagent = "Vicks"
    qa_subagent = "Wedge"
    release_subagent = "Rydia"
    logger.debug(
        "Kosmos task processor ready: base_url={}, roles={}/{}/{}",
        kosmos_api_url,
        dev_subagent,
        qa_subagent,
        release_subagent,
    )

    def _task_status(task: dict[str, Any]) -> str:
        return str(task.get("status") or "").strip().lower()

    def _is_legacy_task_checker_job(job: CronJob) -> bool:
        name = str(job.name or "").strip().lower()
        msg = str(job.payload.message or "").strip().lower()
        if name in {"nanocats-task-checker", "kosmos-task-checker"}:
            return True
        # Legacy checker prompts usually call the task tool directly.
        if "nanocats_tasks" in msg and "list_pending" in msg:
            return True
        if "kosmos" in msg and "task checker" in msg:
            return True
        return False

    def _remove_legacy_task_checker_jobs() -> int:
        removed = 0
        try:
            for existing in cron.list_jobs(include_disabled=True):
                if not _is_legacy_task_checker_job(existing):
                    continue
                result = cron.remove_job(existing.id)
                if result == "removed":
                    removed += 1
                    logger.info(
                        "Removed legacy task checker cron job: {} ({})",
                        existing.name,
                        existing.id,
                    )
                else:
                    logger.warning(
                        "Legacy task checker job not removed ({}): {} ({})",
                        result,
                        existing.name,
                        existing.id,
                    )
        except Exception:
            logger.exception("Failed to cleanup legacy task checker cron jobs")
        return removed

    async def _build_vicks_diff_comment(task_meta: dict[str, Any]) -> str:
        project_id = str(task_meta.get("project_id") or "").strip()
        project_name = str(task_meta.get("project_name") or project_id or "unknown").strip()
        project_path_raw = (
            str(task_meta.get("workspace_path") or "").strip()
            or str(task_meta.get("project_path") or "").strip()
        )
        project_path = (
            Path(project_path_raw)
            if project_path_raw
            else (Path.home() / "proyectos" / project_id if project_id else config.workspace_path)
        )

        if not project_path.exists():
            return (
                "Diff generado automáticamente\n"
                f"Proyecto: {project_name} ({project_id or 'unknown'})\n"
                f"Workspace: {project_path}\n"
                "No se pudo generar diff: el workspace no existe."
            )

        def _run_git(args: list[str]) -> tuple[int, str, str]:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                errors="replace",
            )
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

        rc, inside, _ = await asyncio.to_thread(_run_git, ["rev-parse", "--is-inside-work-tree"])
        if rc != 0 or inside.lower() != "true":
            return (
                "Diff generado automáticamente\n"
                f"Proyecto: {project_name} ({project_id or 'unknown'})\n"
                f"Workspace: {project_path}\n"
                "No se pudo generar diff: el workspace no es un repositorio git."
            )

        _, status_out, _ = await asyncio.to_thread(_run_git, ["status", "--short"])
        _, staged_stat, _ = await asyncio.to_thread(_run_git, ["diff", "--cached", "--stat"])
        _, unstaged_stat, _ = await asyncio.to_thread(_run_git, ["diff", "--stat"])
        _, staged_patch, _ = await asyncio.to_thread(_run_git, ["diff", "--cached", "--no-color"])
        _, unstaged_patch, _ = await asyncio.to_thread(_run_git, ["diff", "--no-color"])

        combined_stat = "\n".join(filter(None, [unstaged_stat, staged_stat]))
        combined_patch = "\n\n".join(filter(None, [unstaged_patch, staged_patch]))
        if len(combined_patch) > 5000:
            combined_patch = combined_patch[:5000].rstrip() + "\n... (diff truncado)"

        return (
            "Diff generado automáticamente\n"
            f"Proyecto: {project_name} ({project_id or 'unknown'})\n"
            f"Workspace: {project_path}\n"
            "\n"
            "Estado git:\n"
            f"{status_out or '(sin cambios detectados)'}\n"
            "\n"
            "Diff --stat:\n"
            f"{combined_stat or '(sin cambios en diff --stat)'}\n"
            "\n"
            "Patch preview:\n"
            f"{combined_patch or '(sin patch disponible)'}"
        )

    async def _build_task_instruction(task: dict[str, Any], role: str) -> str:
        project_id = task.get("project_id") or ""
        project_name = str(task.get("project_name") or "").strip()
        title = task.get("title") or "Untitled task"
        description = task.get("description") or ""
        status = str(task.get("status") or "").strip().lower()
        workspace_path_from_backend = str(task.get("workspace_path") or "").strip()
        project_path_from_backend = str(task.get("project_path") or "").strip()
        workspace_path = (
            workspace_path_from_backend
            or project_path_from_backend
            or (str(Path.home() / "proyectos" / str(project_id)) if project_id else "")
            or str(config.workspace_path)
        )
        role_instruction = (
            "You are Vicks (developer). Implement/fix the task and leave it ready for QA."
            if role == dev_subagent
            else (
                "You are Wedge (code reviewer / QA). Validate implementation, run checks, and approve or report issues."
                if role == qa_subagent
                else (
                    "You are Rydia (release lead). Prepare the final handoff summary and propose conventional commits. "
                    "Do not run git commit or git push until explicit human approval is provided with branch details."
                )
            )
        )
        return (
            f"Resolve Kosmos task {task.get('id')} for project '{project_id}' as {role}.\n"
            f"Project name: {project_name or project_id or 'unknown'}\n"
            f"Title: {title}\n"
            f"Description: {description}\n"
            f"Current Kanban status: {status or 'todo'}\n"
            f"Workspace: {workspace_path}\n"
            f"Project source path (do not edit directly): {project_path_from_backend or '(unknown)'}\n"
            "Requirements:\n"
            f"- {role_instruction}\n"
            "- Work ONLY inside the provided Workspace (git worktree path).\n"
            "- Do NOT modify files directly in the original project source path.\n"
            "- Do NOT call nanocats_tasks claim/qa/release/done (workflow transitions are managed by Kosmos gateway).\n"
            "- If edit_file fails with old_text/oldString not found, re-read the exact file and retry with a smaller exact anchor.\n"
            "- Always use complete file paths with extension (never truncated paths like src/components/Task).\n"
            "- Do the implementation work needed to complete this task.\n"
            "- Run relevant checks/tests when applicable.\n"
            "- Return a concise completion report with what changed and verification status."
        )

    def _resolve_project_path(task: dict[str, Any]) -> Path:
        project_id = str(task.get("project_id") or "").strip()
        project_path_from_backend = str(task.get("project_path") or "").strip()
        if project_path_from_backend:
            return Path(project_path_from_backend)
        if project_id:
            return Path.home() / "proyectos" / project_id
        return config.workspace_path

    def _workspace_root() -> Path:
        return Path.home() / ".nanobot" / "worktrees"

    def _slugify(value: str, limit: int = 42) -> str:
        raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
        while "--" in raw:
            raw = raw.replace("--", "-")
        raw = raw.strip("-")
        if not raw:
            return "task"
        return raw[:limit].rstrip("-")

    def _branch_prefix_from_task(task: dict[str, Any]) -> str:
        title = str(task.get("title") or "").lower()
        desc = str(task.get("description") or "").lower()
        text = f"{title}\n{desc}"
        if any(k in text for k in ["bug", "fix", "error", "issue", "hotfix", "broken"]):
            return "fix"
        return "feature"

    def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def _ensure_task_worktree(task: dict[str, Any]) -> tuple[bool, dict[str, str], str]:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return False, {}, "missing task id"

        existing_workspace = str(task.get("workspace_path") or "").strip()
        existing_branch = str(task.get("work_branch") or "").strip()
        existing_base = str(task.get("base_branch") or "").strip()
        if existing_workspace and existing_branch:
            p = Path(existing_workspace)
            if p.exists() and (p / ".git").exists():
                return (
                    True,
                    {
                        "workspace_path": str(p),
                        "work_branch": existing_branch,
                        "base_branch": existing_base,
                    },
                    "",
                )

        project_path = _resolve_project_path(task)
        if not project_path.exists() or not project_path.is_dir():
            return False, {}, f"project path missing: {project_path}"

        code, base_branch, err = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_path)
        if code != 0 or not base_branch:
            return False, {}, f"failed to detect base branch: {err or 'unknown git error'}"

        prefix = _branch_prefix_from_task(task)
        task_title = str(task.get("title") or "task")
        slug = _slugify(task_title)
        digest = hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:8]
        work_branch = f"{prefix}/{slug}-{digest}"

        work_root = _workspace_root()
        work_root.mkdir(parents=True, exist_ok=True)
        workspace_path = work_root / task_id

        if workspace_path.exists() and not (workspace_path / ".git").exists():
            return False, {}, f"workspace exists but is not a git checkout: {workspace_path}"

        if workspace_path.exists() and (workspace_path / ".git").exists():
            return (
                True,
                {
                    "workspace_path": str(workspace_path),
                    "work_branch": work_branch,
                    "base_branch": base_branch,
                },
                "",
            )

        # Ensure branch exists from base branch tip.
        branch_code, _, _ = _run_git(["rev-parse", "--verify", work_branch], project_path)
        if branch_code != 0:
            create_code, _, create_err = _run_git(
                ["branch", work_branch, base_branch],
                project_path,
            )
            if create_code != 0:
                return False, {}, f"failed creating branch {work_branch}: {create_err}"

        add_code, _, add_err = _run_git(
            ["worktree", "add", str(workspace_path), work_branch],
            project_path,
        )
        if add_code != 0:
            return False, {}, f"failed creating worktree: {add_err}"

        return (
            True,
            {
                "workspace_path": str(workspace_path),
                "work_branch": work_branch,
                "base_branch": base_branch,
            },
            "",
        )

    def _read_text_safe(path: Path, limit: int = 4000) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        text = text.strip()
        if len(text) > limit:
            return text[:limit].rstrip() + "\n... (truncated)"
        return text

    def _build_agents_md(project_path: Path, project_name: str) -> str:
        key_files = [
            "README.md",
            "README",
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "Makefile",
            "docker-compose.yml",
            "Dockerfile",
        ]
        found_files: list[Path] = []
        for name in key_files:
            p = project_path / name
            if p.exists() and p.is_file():
                found_files.append(p)

        top_entries: list[str] = []
        try:
            for child in sorted(project_path.iterdir(), key=lambda p: p.name.lower()):
                if child.name.startswith("."):
                    continue
                suffix = "/" if child.is_dir() else ""
                top_entries.append(f"- {child.name}{suffix}")
                if len(top_entries) >= 40:
                    break
        except Exception:
            top_entries = ["- (could not scan project root)"]

        snippets: list[str] = []
        for p in found_files:
            body = _read_text_safe(p, limit=2500)
            if not body:
                continue
            snippets.append(f"### {p.name}\n\n```text\n{body}\n```")

        snippets_block = "\n\n".join(snippets) if snippets else "No key files were readable."
        top_block = "\n".join(top_entries) if top_entries else "- (empty project root)"

        return (
            f"# AGENTS.md\n\n"
            f"Project: {project_name or project_path.name}\n"
            f"Path: {project_path}\n\n"
            "## Purpose\n"
            "This file gives execution context to Kosmos subagents (Vicks, Wedge, Rydia).\n"
            "Read this first before making code changes.\n\n"
            "## Project Root Snapshot\n"
            f"{top_block}\n\n"
            "## Working Agreement\n"
            "- Keep changes scoped to the assigned task.\n"
            "- Prefer existing patterns over introducing new architecture.\n"
            "- Run relevant checks before marking work complete.\n"
            "- Document assumptions in task comments.\n\n"
            "## Key Files Context\n\n"
            f"{snippets_block}\n"
        )

    def _normalize_jira_description(task: dict[str, Any], original: str) -> str:
        title = str(task.get("title") or "Untitled task").strip()
        project_id = str(task.get("project_id") or "").strip()
        status = str(task.get("status") or "todo").strip().lower()
        orig = original.strip() or "No original description provided."

        def _summary_from_original(text: str) -> str:
            base = " ".join(line.strip() for line in text.splitlines() if line.strip())
            if not base:
                return "Implement the task using current project patterns and verify expected behavior."

            pieces: list[str] = []
            for separator in [". ", "? ", "! "]:
                if separator in base:
                    parts = [p.strip() for p in base.split(separator) if p.strip()]
                    for part in parts:
                        if part[-1:] not in {".", "?", "!"}:
                            part = part + "."
                        pieces.append(part)
                    break

            if not pieces:
                pieces = [base if base[-1:] in {".", "?", "!"} else base + "."]

            summary = " ".join(pieces[:2])
            if len(summary) > 300:
                summary = summary[:300].rstrip() + "..."
            return summary

        summary_seed = _summary_from_original(orig)

        return (
            f"# {title}\n"
            f"{summary_seed}\n\n"
            "## Contexto y motivación\n"
            "¿Por qué se necesita? ¿Qué problema resuelve?\n\n"
            "**Contexto actual:**\n"
            f"- Proyecto: {project_id or 'unknown'}\n"
            f"- Estado actual: {status or 'todo'}\n"
            "- Esta tarea fue normalizada por Kosmos para ejecución consistente.\n"
            "- Descripción original preservada al final para trazabilidad.\n\n"
            "## Criterios de éxito\n"
            "- Métricas cuantificables\n"
            "- La funcionalidad objetivo está operativa end-to-end\n"
            "- Pruebas/checks relevantes ejecutados sin errores críticos\n"
            "- Resultado verificable documentado en comentarios de tarea\n\n"
            "## Requisitos funcionales\n"
            "- Comportamientos esperados\n"
            "- Implementar únicamente lo necesario para cumplir el objetivo\n"
            "- Mantener compatibilidad con el flujo actual del proyecto\n\n"
            "## Restricciones\n"
            "- Stack, APIs, patrones del proyecto\n"
            "- Respetar convenciones existentes de arquitectura y estilo\n"
            "- Evitar cambios no relacionados al alcance definido\n\n"
            "## Fuera de alcance ⚠️\n"
            "- Qué NO construir\n"
            "- No introducir refactors masivos fuera del problema objetivo\n"
            "- No cambiar contratos públicos sin justificación explícita\n\n"
            "## Criterios de aceptación\n"
            "- Given/When/Then verificables\n"
            "- Given el estado actual del proyecto, When se implementa la solución, Then el comportamiento esperado funciona correctamente\n"
            "- Given casos de validación relevantes, When se ejecutan checks/tests, Then no hay fallas bloqueantes\n"
            "- Given los cambios completados, When se revisa la tarea, Then existe evidencia clara de verificación\n\n"
            "## Descripción original\n"
            f"{orig}\n"
        )

    async def _prepare_todo_task(task: dict[str, Any]) -> tuple[bool, str]:
        task_id = str(task.get("id") or "")
        project_id = str(task.get("project_id") or "")
        project_name = str(task.get("project_name") or project_id or "unknown")
        if not task_id:
            return False, "Kosmos heartbeat: invalid todo task id."

        project_path = _resolve_project_path(task)
        agents_md_path = project_path / "AGENTS.md"
        if not project_path.exists() or not project_path.is_dir():
            await kosmos_tasks.create_task_comment(
                task_id=task_id,
                agent_id="Kosmos",
                comment=(f"Project workspace not found. Expected path: {project_path}"),
            )
            await kosmos_tasks.publish_activity(
                {
                    "id": f"precheck-path-missing-{task_id}",
                    "agentId": "Kosmos",
                    "agentName": "Kosmos",
                    "projectId": project_id,
                    "taskId": task_id,
                    "type": "status",
                    "status": "blocked",
                    "currentTask": f"Workspace missing for {task_id}",
                    "mood": "focused",
                    "message": f"Workspace not found: {project_path}",
                }
            )
            return False, f"Kosmos heartbeat: workspace not found for task {task_id}."

        if not (project_path / ".git").exists():
            await kosmos_tasks.create_task_comment(
                task_id=task_id,
                agent_id="Kosmos",
                comment=(
                    f"Project workspace is not a git repository. Expected path: {project_path}"
                ),
            )
            await kosmos_tasks.publish_activity(
                {
                    "id": f"precheck-not-git-{task_id}",
                    "agentId": "Kosmos",
                    "agentName": "Kosmos",
                    "projectId": project_id,
                    "taskId": task_id,
                    "type": "status",
                    "status": "blocked",
                    "currentTask": f"Non-git workspace for {task_id}",
                    "mood": "confused",
                    "message": f"Not a git repository: {project_path}",
                }
            )
            return False, f"Kosmos heartbeat: not a git repository for task {task_id}."

        code_uname, git_user_name, err_uname = _run_git(
            ["config", "--local", "user.name"], project_path
        )
        code_uemail, git_user_email, err_uemail = _run_git(
            ["config", "--local", "user.email"], project_path
        )
        if code_uname != 0 or not git_user_name:
            code_uname, git_user_name, err_uname = _run_git(
                ["config", "--global", "user.name"], project_path
            )
        if code_uemail != 0 or not git_user_email:
            code_uemail, git_user_email, err_uemail = _run_git(
                ["config", "--global", "user.email"], project_path
            )
        if not git_user_name or not git_user_email:
            await kosmos_tasks.create_task_comment(
                task_id=task_id,
                agent_id="Kosmos",
                comment=(
                    "Git user not configured for this project. "
                    f"Please run: git config --local user.name 'Your Name' && git config --local user.email 'your@email.com' "
                    f"in {project_path}"
                ),
            )
            await kosmos_tasks.publish_activity(
                {
                    "id": f"precheck-git-config-{task_id}",
                    "agentId": "Kosmos",
                    "agentName": "Kosmos",
                    "projectId": project_id,
                    "taskId": task_id,
                    "type": "status",
                    "status": "blocked",
                    "currentTask": f"Git not configured for {task_id}",
                    "mood": "confused",
                    "message": f"Git user not configured. Run git config in {project_path}",
                }
            )
            return False, f"Kosmos heartbeat: git user not configured for task {task_id}."

        ok_worktree, worktree_meta, worktree_error = _ensure_task_worktree(task)
        if not ok_worktree:
            await kosmos_tasks.create_task_comment(
                task_id=task_id,
                agent_id="Kosmos",
                comment=(f"Failed to create task worktree/branch. Error: {worktree_error}"),
            )
            return False, f"Kosmos heartbeat: worktree precheck failed for task {task_id}."

        await kosmos_tasks.update_task(
            task_id,
            workspace_path=worktree_meta.get("workspace_path"),
            work_branch=worktree_meta.get("work_branch"),
            base_branch=worktree_meta.get("base_branch"),
        )

        if not agents_md_path.exists():
            logger.info(
                "Kosmos preflight: generating AGENTS.md for {} at {}", task_id, project_path
            )
            agents_md_content = _build_agents_md(project_path, project_name)
            try:
                agents_md_path.write_text(agents_md_content, encoding="utf-8")
            except Exception as e:
                await kosmos_tasks.create_task_comment(
                    task_id=task_id,
                    agent_id="Kosmos",
                    comment=(f"Failed to create AGENTS.md before task execution. Error: {e}"),
                )
                return False, f"Kosmos heartbeat: failed creating AGENTS.md for task {task_id}."

            await kosmos_tasks.create_task_comment(
                task_id=task_id,
                agent_id="Kosmos",
                comment=(
                    "[KOSMOS_CONTEXT_READY] AGENTS.md was created and project context is now available. "
                    "Task execution will continue on next heartbeat."
                ),
            )
            await kosmos_tasks.publish_activity(
                {
                    "id": f"precheck-context-created-{task_id}",
                    "agentId": "Kosmos",
                    "agentName": "Kosmos",
                    "projectId": project_id,
                    "taskId": task_id,
                    "type": "status",
                    "status": "waiting",
                    "currentTask": f"Context prepared for {task_id}",
                    "mood": "focused",
                    "message": "AGENTS.md created; waiting next tick to continue.",
                }
            )
            return False, f"Kosmos heartbeat: created AGENTS.md for task {task_id}."

        description = str(task.get("description") or "")
        jira_ready = bool(task.get("jira_ready"))
        if not jira_ready:
            jira_description = _normalize_jira_description(task, description)
            updated = await kosmos_tasks.update_task(
                task_id,
                description=jira_description,
                jira_ready=True,
            )
            if not updated:
                return (
                    False,
                    f"Kosmos heartbeat: failed to normalize task {task_id} to Jira format.",
                )
            await kosmos_tasks.create_task_comment(
                task_id=task_id,
                agent_id="Kosmos",
                comment=(
                    "Task description normalized to Jira format "
                    "(summary, scope, acceptance criteria, DoD, original description)."
                ),
            )
            await kosmos_tasks.publish_activity(
                {
                    "id": f"precheck-jira-normalized-{task_id}",
                    "agentId": "Kosmos",
                    "agentName": "Kosmos",
                    "projectId": project_id,
                    "taskId": task_id,
                    "type": "status",
                    "status": "waiting",
                    "currentTask": f"Task {task_id} normalized",
                    "mood": "focused",
                    "message": "Task rewritten to Jira format; waiting next tick.",
                }
            )
            return False, f"Kosmos heartbeat: normalized task {task_id} to Jira format."

        return True, ""

    def _is_frontend_task(task_meta: dict[str, Any]) -> bool:
        project_path_raw = (
            str(task_meta.get("workspace_path") or "").strip()
            or str(task_meta.get("project_path") or "").strip()
        )
        if not project_path_raw:
            return False
        p = Path(project_path_raw)
        if not p.exists():
            return False
        frontend_indicators = (
            (p / "package.json").exists()
            or (p / "vite.config.ts").exists()
            or (p / "vite.config.js").exists()
            or (p / "src" / "App.tsx").exists()
            or (p / "src" / "main.tsx").exists()
            or (p / "src" / "index.tsx").exists()
        )
        return frontend_indicators

    async def _collect_and_upload_artifacts(
        result_text: str,
        kanban_task_id: str,
        agent_name: str,
        workspace_path: str,
    ) -> list[dict[str, Any]]:
        """Parse artifact paths from subagent output and upload to Kosmos."""
        uploaded = []
        if not result_text:
            return uploaded

        possible_roots: list[Path] = []
        if workspace_path:
            possible_roots.append(Path(workspace_path))
        possible_roots.append(Path.home() / ".nanobot" / "artifacts" / kanban_task_id)

        artifact_paths: list[tuple[str, Path]] = []
        for line in result_text.splitlines():
            line = line.strip()
            for suffix in (".png", ".jpg", ".jpeg", ".webp"):
                if suffix in line:
                    idx = line.find(suffix)
                    maybe_path = line[max(0, idx - 200) : idx + len(suffix)].strip()
                    for root in possible_roots:
                        if root.exists():
                            candidate = root / Path(maybe_path).name
                            if candidate.exists():
                                artifact_paths.append((candidate.name, candidate))
                                break
                    break

        for filename, file_path in artifact_paths[:6]:
            try:
                artifact = await kosmos_tasks.upload_artifact(
                    task_id=kanban_task_id,
                    file_path=str(file_path),
                    filename=filename,
                    created_by=agent_name,
                )
                if artifact:
                    uploaded.append(artifact)
            except Exception:
                logger.warning("Failed to upload artifact {} for task {}", filename, kanban_task_id)

        return uploaded

    async def _on_subagent_task_complete(payload: dict[str, Any]) -> None:
        task_meta = payload.get("task_meta") or {}
        kanban_task_id = task_meta.get("kanban_task_id")
        if not kanban_task_id:
            return
        status = payload.get("status")
        role = str(task_meta.get("subagent_name") or "")
        logger.info(
            "Subagent completion callback: runtime_id={} role={} status={} task_id={} project_id={}",
            payload.get("task_id", ""),
            role,
            status,
            kanban_task_id,
            task_meta.get("project_id", ""),
        )
        active_subagent_roles.discard(role)
        runtime_subagent_id = str(payload.get("subagent_runtime_id") or "")
        reviewer = runtime_subagent_id if runtime_subagent_id else role or "nanobot"
        result_preview = str(payload.get("result") or "")
        headline = "Completed successfully" if status == "ok" else "Failed / needs follow-up"
        transition = "status unchanged"
        body = (
            result_preview[:900].strip() if result_preview else "No detailed output was produced."
        )
        max_retry_count = int(getattr(config.gateway, "task_retry_limit", 3) or 3)

        def _looks_like_non_blocking_edit_anchor_error(text: str) -> bool:
            t = (text or "").lower()
            if "old_text not found" in t or "oldstring not found" in t:
                return True
            if "edit_file" in t and "not found" in t and "src/components/task" in t:
                return True
            return False

        async def _notify_release_approval_prompt(task_snapshot: dict[str, Any] | None) -> None:
            if role != release_subagent:
                return
            if not task_snapshot:
                return
            if bool(task_snapshot.get("release_approved")):
                return

            task_id = str(task_snapshot.get("id") or kanban_task_id)
            task_title = str(task_snapshot.get("title") or "Task")
            work_branch = str(task_snapshot.get("work_branch") or "").strip()
            base_branch = str(task_snapshot.get("base_branch") or "").strip()

            msg = (
                "Rydia terminó el release y está listo para aprobación humana.\n\n"
                f"Task: {task_id} - {task_title}\n"
                f"Rama de trabajo temporal: {work_branch or '(no definida)'}\n"
                f"Rama base: {base_branch or '(no definida)'}\n\n"
                "Responde con una de estas opciones:\n"
                "1) Aprobar en rama temporal (sin push):\n"
                f"   nanobot approve-release {task_id} --branch {work_branch or 'feature/...'} --no-push\n"
                "2) Aprobar en rama temporal (con push):\n"
                f"   nanobot approve-release {task_id} --branch {work_branch or 'feature/...'} --push\n"
                "3) Aprobar en otra rama:\n"
                f"   nanobot approve-release {task_id} --branch <rama-destino> --push\n"
            )

            from nanobot.bus.events import OutboundMessage

            channel, chat_id = _pick_heartbeat_target()
            if channel != "cli":
                await bus.publish_outbound(
                    OutboundMessage(channel=channel, chat_id=chat_id, content=msg)
                )

        comment_text = f"{headline}\n\n{body}"
        if status == "ok" and role == dev_subagent:
            diff_comment = await _build_vicks_diff_comment(task_meta)
            comment_text = f"{comment_text}\n\n{diff_comment}"

        if status == "ok" and role == qa_subagent and _is_frontend_task(task_meta):
            workspace_path = str(task_meta.get("workspace_path") or "")
            uploaded = await _collect_and_upload_artifacts(
                result_preview,
                str(kanban_task_id),
                role,
                workspace_path,
            )
            if uploaded:
                lines = ["\n\n## Evidencia visual\n"]
                for art in uploaded:
                    art_id = art.get("id", "")
                    filename = art.get("filename", "")
                    lines.append(f"![{filename}](/api/artifacts/{art_id})")
                comment_text = f"{comment_text}\n\n" + "\n".join(lines)

        # Ensure identities exist for backend ACL checks on comments.
        if runtime_subagent_id:
            await kosmos_tasks.upsert_agent_identity(
                agent_id=runtime_subagent_id,
                agent_name=role or runtime_subagent_id,
                project_id=str(task_meta.get("project_id") or ""),
                status="coding" if role == dev_subagent else "consulting",
                mood="focused",
                current_task=str(task_meta.get("title") or "Task"),
            )
        if role in {dev_subagent, qa_subagent, release_subagent}:
            await kosmos_tasks.upsert_agent_identity(
                agent_id=role,
                agent_name=role,
                project_id=str(task_meta.get("project_id") or ""),
                status="coding" if role == dev_subagent else "consulting",
                mood="focused",
                current_task=str(task_meta.get("title") or "Task"),
            )

        async def _ensure_assigned_to(expected_name: str) -> bool:
            task_snapshot = await kosmos_tasks.get_task(str(kanban_task_id))
            if not task_snapshot:
                logger.warning("Task {} not found before comment", kanban_task_id)
                return False
            current_assigned = str(task_snapshot.get("assigned_to") or "").strip()
            if current_assigned.lower() != expected_name.lower():
                updated = await kosmos_tasks.update_task(
                    str(kanban_task_id),
                    assigned_to=expected_name,
                )
                if not updated:
                    logger.warning(
                        "Task {} assigned_to mismatch and could not be fixed (wanted={}, had={})",
                        kanban_task_id,
                        expected_name,
                        current_assigned,
                    )
                    return False
            return True

        # Comment as the assigned subagent before changing status.
        expected_owner_for_comment = (
            role if role in {dev_subagent, qa_subagent, release_subagent} else reviewer
        )
        owner_ok = await _ensure_assigned_to(expected_owner_for_comment)
        if not owner_ok:
            logger.warning(
                "Task {} completion skipped because owner check failed for {}",
                kanban_task_id,
                expected_owner_for_comment,
            )
            return

        created_comment = await kosmos_tasks.create_task_comment(
            task_id=str(kanban_task_id),
            agent_id=expected_owner_for_comment,
            comment=comment_text,
        )

        # Enforce rule: task completion requires a comment.
        if not created_comment:
            logger.warning(
                "Task {} completion skipped because comment creation failed (agent_id={}, role={})",
                kanban_task_id,
                reviewer,
                role,
            )
            return

        if status == "ok":
            await kosmos_tasks.update_task(
                str(kanban_task_id),
                retry_count=0,
                last_failure_reason="",
            )
            if role == dev_subagent:
                transition = "in progress -> qa"
                await kosmos_tasks.transition_task(
                    kanban_task_id,
                    to_status="qa",
                    comment_text=f"Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to=qa_subagent,
                )
                await kosmos_tasks.update_task(
                    str(kanban_task_id),
                    retry_count=0,
                    last_failure_reason="",
                )
            elif role == qa_subagent:
                transition = "qa -> release"
                await kosmos_tasks.transition_task(
                    kanban_task_id,
                    to_status="release",
                    comment_text=f"Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to=release_subagent,
                )
                await kosmos_tasks.update_task(
                    str(kanban_task_id),
                    retry_count=0,
                    last_failure_reason="",
                )
            else:
                task_snapshot = await kosmos_tasks.get_task(str(kanban_task_id))
                approved = bool((task_snapshot or {}).get("release_approved"))
                if approved:
                    transition = "release -> done"
                    await kosmos_tasks.transition_task(
                        kanban_task_id,
                        to_status="done",
                        comment_text=f"Transition: {transition}\n\n{body}",
                        agent_id=role,
                        agent_name=role,
                        assigned_to=release_subagent,
                    )
                else:
                    transition = "release -> release (awaiting human approval)"
                    await kosmos_tasks.update_task(
                        kanban_task_id,
                        assigned_to=release_subagent,
                    )
                    await kosmos_tasks.create_task_comment(
                        task_id=str(kanban_task_id),
                        agent_id=release_subagent,
                        comment=(
                            "Release prepared. Waiting for explicit human approval "
                            "(approved_by, branch, push) before moving to done.\n\n"
                            f"{body}"
                        ),
                    )
                    refreshed = await kosmos_tasks.get_task(str(kanban_task_id))
                    await _notify_release_approval_prompt(refreshed)
        else:
            if role == dev_subagent and _looks_like_non_blocking_edit_anchor_error(body):
                snapshot = await kosmos_tasks.get_task(str(kanban_task_id))
                retry_count = int(snapshot.get("retry_count") or 0) if snapshot else 0
                retry_count += 1
                if retry_count >= max_retry_count:
                    transition = "in progress -> todo (retry limit reached)"
                    await kosmos_tasks.transition_task(
                        kanban_task_id,
                        to_status="todo",
                        comment_text=(
                            f"Transition: {transition}\n\n"
                            f"Automatic retry limit reached ({retry_count}/{max_retry_count}) for edit anchor mismatch.\n\n{body}"
                        ),
                        agent_id=role,
                        agent_name=role,
                        assigned_to="",
                    )
                    await kosmos_tasks.update_task(
                        str(kanban_task_id),
                        retry_count=0,
                        last_failure_reason="edit_anchor_mismatch",
                    )
                else:
                    transition = "in progress -> in progress (retry required: edit anchor mismatch)"
                    await kosmos_tasks.update_task(
                        kanban_task_id,
                        status="progress",
                        assigned_to=dev_subagent,
                        retry_count=retry_count,
                        last_failure_reason="edit_anchor_mismatch",
                    )
                    await kosmos_tasks.create_task_comment(
                        task_id=str(kanban_task_id),
                        agent_id=dev_subagent,
                        comment=(
                            "Detected edit anchor mismatch (old_text not found). "
                            "Keeping task in progress for automatic retry in the same worktree "
                            f"({retry_count}/{max_retry_count})."
                        ),
                    )
            elif role == release_subagent:
                transition = "release -> release (needs follow-up)"
                await kosmos_tasks.update_task(
                    kanban_task_id,
                    status="release",
                    assigned_to=release_subagent,
                )
                await kosmos_tasks.create_task_comment(
                    task_id=str(kanban_task_id),
                    agent_id=release_subagent,
                    comment=(
                        "Release step reported a non-fatal failure. "
                        "Task stays in release for retry/follow-up instead of returning to todo."
                    ),
                )
            elif role == dev_subagent:
                transition = "in progress -> todo"
                await kosmos_tasks.transition_task(
                    kanban_task_id,
                    to_status="todo",
                    comment_text=f"Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to="",
                )
            elif role == qa_subagent:
                transition = "qa -> todo"
                await kosmos_tasks.transition_task(
                    kanban_task_id,
                    to_status="todo",
                    comment_text=f"Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to="",
                )
            else:
                transition = "release -> todo"
                await kosmos_tasks.transition_task(
                    kanban_task_id,
                    to_status="todo",
                    comment_text=f"Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to="",
                )

        # Keep handoff comments aligned with the current assignee after transition.
        if role in {dev_subagent, qa_subagent, release_subagent}:
            post_transition = await kosmos_tasks.get_task(str(kanban_task_id))
            handoff_owner = str((post_transition or {}).get("assigned_to") or "").strip() or role
            owner_ok = await _ensure_assigned_to(handoff_owner)
            if not owner_ok:
                logger.warning(
                    "Task {} transition comment skipped because owner check failed for {}",
                    kanban_task_id,
                    handoff_owner,
                )
                return

            transition_comment = f"Handoff note: {transition}\n\n{body}"
            transition_comment_created = await kosmos_tasks.create_task_comment(
                task_id=str(kanban_task_id),
                agent_id=handoff_owner,
                comment=transition_comment,
            )
            if not transition_comment_created:
                logger.warning(
                    "Task {} transition comment missing for handoff owner {} ({})",
                    kanban_task_id,
                    handoff_owner,
                    transition,
                )

        project_id = str(task_meta.get("project_id") or "")
        title = str(task_meta.get("title") or "Task")
        done_message = f"{title} - {transition}"
        await kosmos_tasks.publish_activity(
            {
                "id": f"task-end-{kanban_task_id}",
                "agentId": payload.get("task_id", "main"),
                "agentName": payload.get("label", "Subagent"),
                "projectId": project_id,
                "type": "status",
                "status": "resting",
                "currentTask": "",
                "mood": "sleepy",
                "message": done_message,
            }
        )

        # Despawn/idle bookkeeping: once a subagent finishes, mark it as resting
        # so the UI and scheduler do not keep showing it as active.
        try:
            if runtime_subagent_id:
                await kosmos_tasks.upsert_agent_identity(
                    agent_id=runtime_subagent_id,
                    agent_name=role or runtime_subagent_id,
                    project_id=str(task_meta.get("project_id") or ""),
                    status="resting",
                    mood="sleepy",
                    current_task="",
                )
            if role in {dev_subagent, qa_subagent, release_subagent}:
                await kosmos_tasks.upsert_agent_identity(
                    agent_id=role,
                    agent_name=role,
                    project_id=str(task_meta.get("project_id") or ""),
                    status="resting",
                    mood="sleepy",
                    current_task="",
                )
        except Exception:
            logger.exception(
                "Failed to mark subagent as resting after completion: role={} runtime_id={}",
                role,
                runtime_subagent_id,
            )

    async def _on_subagent_task_start(payload: dict[str, Any]) -> None:
        task_meta = payload.get("task_meta") or {}
        kanban_task_id = task_meta.get("kanban_task_id")
        if not kanban_task_id:
            return
        role = str(task_meta.get("subagent_name") or "")
        logger.info(
            "Subagent start callback: runtime_id={} role={} task_id={} project_id={}",
            payload.get("task_id", ""),
            role,
            kanban_task_id,
            task_meta.get("project_id", ""),
        )
        if role:
            active_subagent_roles.add(role)

        # Keep the task owner aligned with the running subagent.
        await kosmos_tasks.update_task(
            kanban_task_id,
            assigned_to=role or str(payload.get("task_id") or "nanobot"),
        )

        target_status = (
            "progress" if role == dev_subagent else ("qa" if role == qa_subagent else "release")
        )
        await kosmos_tasks.transition_task(
            kanban_task_id,
            to_status=target_status,
            comment_text=f"Started work in {target_status}.",
            agent_id=role or str(payload.get("task_id") or "nanobot"),
            agent_name=role or str(payload.get("label") or "nanobot"),
            assigned_to=role or str(payload.get("task_id") or "nanobot"),
        )

        project_id = str(task_meta.get("project_id") or "")
        title = str(task_meta.get("title") or "Working on task")
        await kosmos_tasks.publish_activity(
            {
                "id": f"task-start-{kanban_task_id}",
                "agentId": payload.get("task_id", "main"),
                "agentName": payload.get("label", "Subagent"),
                "projectId": project_id,
                "type": "coding",
                "status": "coding",
                "currentTask": title,
                "mood": "focused",
                "message": title,
            }
        )

    if subagents and hasattr(subagents, "set_on_task_start"):
        subagents.set_on_task_start(_on_subagent_task_start)
    if subagents and hasattr(subagents, "set_on_task_complete"):
        subagents.set_on_task_complete(_on_subagent_task_complete)

    async def _on_task_deleted(kanban_task_id: str) -> None:
        logger.warning("Kanban task {} was deleted while a subagent was running", kanban_task_id)
        try:
            await kosmos_tasks.create_task_comment(
                task_id=kanban_task_id,
                agent_id="Kosmos",
                comment=(
                    "Task was deleted from the kanban board. "
                    "The subagent working on this task has been stopped."
                ),
            )
        except Exception:
            pass

    if subagents and hasattr(subagents, "set_on_task_deleted"):
        subagents.set_on_task_deleted(_on_task_deleted)

    kosmos_ws_url = kosmos_api_url.replace("http://", "ws://").replace("https://", "wss://")
    kosmos_ws: Any = None

    async def _listen_kosmos_events() -> None:
        nonlocal kosmos_ws
        import aiohttp

        ws_url = f"{kosmos_ws_url.replace('http', 'ws')}:{int(kosmos_api_url.split(':')[-1]) + 1}/ws?client_id=nanobot-main"
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(ws_url) as ws:
                        kosmos_ws = ws
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                import json

                                try:
                                    data = json.loads(msg.data)
                                    if data.get("type") == "task:deleted":
                                        task_id = data.get("payload", {}).get("id")
                                        if task_id and subagents:
                                            await subagents.notify_task_deleted(task_id)
                                except Exception:
                                    pass
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                break
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    events_listener = asyncio.create_task(_listen_kosmos_events())

    def _running_subagent_count() -> int:
        if not subagents or not hasattr(subagents, "get_running_count"):
            return 0
        try:
            return int(subagents.get_running_count())
        except Exception:
            return 0

    def _is_role_running(role: str) -> bool:
        if role in active_subagent_roles:
            return True
        if not subagents:
            return False
        running_roles = getattr(subagents, "_running_roles", None)
        if isinstance(running_roles, dict):
            return role in running_roles
        return False

    def _is_kanban_task_running(task_id: str) -> bool:
        if not task_id or not subagents:
            return False
        running_map = getattr(subagents, "_running_kanban_tasks", None)
        if isinstance(running_map, dict):
            return task_id in running_map
        return False

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        logger.info("Cron tick: id={} name={} kind={}", job.id, job.name, job.schedule.kind)
        # Dream is an internal job — run directly, not through the agent loop.
        if job.name == "dream":
            try:
                await agent.dream.run()
                logger.info("Dream cron job completed")
            except Exception:
                logger.exception("Dream cron job failed")
            return None

        if _is_legacy_task_checker_job(job):
            logger.info(
                "Routing legacy task checker cron job to heartbeat preflight flow: {} ({})",
                job.name,
                job.id,
            )
            try:
                routed = await on_heartbeat_execute("")
            except Exception:
                logger.exception(
                    "Legacy task checker routing failed for {} ({})",
                    job.name,
                    job.id,
                )
                return "Kosmos heartbeat routing failed."

            # Keep cron session stateless even for routed executions.
            session_key = f"cron:{job.id}"
            try:
                cron_session = agent.sessions.get_or_create(session_key)
                cron_session.clear()
                agent.sessions.save(cron_session)
                agent.sessions.invalidate(session_key)
            except Exception:
                logger.exception("Failed to clear cron session {}", session_key)
            return routed

        session_key = f"cron:{job.id}"

        # Hard guard: cron must not start a new planning turn while any
        # subagent is still running. This keeps execution strictly serial and
        # avoids duplicate dispatches on frequent schedules.
        running_subagents = _running_subagent_count()
        if running_subagents > 0:
            logger.info(
                "Cron skip: {} running subagent(s); job={} ({})",
                running_subagents,
                job.id,
                job.name,
            )
            active_task_id = ""
            active_project_id = ""
            active_role = ""
            try:
                pending_tasks = await kosmos_tasks.list_pending_tasks()
                active_candidates = [
                    t
                    for t in pending_tasks
                    if _task_status(t) in {"progress", "in_progress", "qa", "release"}
                    and str(t.get("assigned_to") or "")
                    in {dev_subagent, qa_subagent, release_subagent}
                ]
                if active_candidates:
                    active = active_candidates[0]
                    active_task_id = str(active.get("id") or "")
                    active_project_id = str(active.get("project_id") or "")
                    active_role = str(active.get("assigned_to") or "")
            except Exception:
                logger.exception("Failed to resolve active task context for cron skip")

            try:
                active_suffix = (
                    f" [{active_role}:{active_task_id}]" if active_task_id and active_role else ""
                )
                await kosmos_tasks.publish_activity(
                    {
                        "id": f"cron-skip-{job.id}",
                        "agentId": "cron",
                        "agentName": "Kosmos Task Checker",
                        "projectId": active_project_id,
                        "taskId": active_task_id,
                        "type": "status",
                        "status": "waiting",
                        "currentTask": (
                            f"Cron skipped: {running_subagents} subagent(s) active{active_suffix}"
                        ),
                        "mood": "focused",
                        "message": (
                            "0 acciones - subagente activo"
                            + (f" ({active_role} -> {active_task_id})" if active_task_id else "")
                        ),
                    }
                )
            except Exception:
                logger.exception("Failed to publish cron skip activity")

            try:
                cron_session = agent.sessions.get_or_create(session_key)
                cron_session.clear()
                agent.sessions.save(cron_session)
                agent.sessions.invalidate(session_key)
            except Exception:
                logger.exception("Failed to clear cron session {}", session_key)
            return f"0 acciones - subagente activo ({running_subagents})"

        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.message import MessageTool
        from nanobot.utils.evaluator import evaluate_response

        scheduled_context = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        reminder_note = (
            f"{scheduled_context}\n\n"
            "[CRON RUNTIME OVERRIDES - OBLIGATORIO]\n"
            "- Ignora cualquier preferencia histórica de proyecto en MEMORY.md para esta ejecución.\n"
            "- No asumas proyecto por defecto (ej: fractalmind).\n"
            "- Primero usa nanocats_tasks(action='list_pending').\n"
            "- Solo usa nanocats_tasks(action='list_project', project_id=...) si ese project_id proviene de una tarea pendiente real.\n"
            "- Si no hay pendientes accionables, responde exactamente: 0 acciones."
        )

        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            logger.debug("Cron executing agent turn: job={} ({})", job.id, job.name)
            resp = await agent.process_direct(
                reminder_note,
                session_key=session_key,
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

            # Cron jobs should be stateless between runs. Persisted session
            # context can make future executions act on stale assumptions.
            try:
                cron_session = agent.sessions.get_or_create(session_key)
                cron_session.clear()
                agent.sessions.save(cron_session)
                agent.sessions.invalidate(session_key)
            except Exception:
                logger.exception("Failed to clear cron session {}", session_key)

        response = resp.content if resp else ""
        logger.info(
            "Cron completed: job={} ({}) response_chars={}",
            job.id,
            job.name,
            len(response or ""),
        )

        message_tool = agent.tools.get("message")
        if job.payload.deliver and isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            should_notify = await evaluate_response(
                response,
                scheduled_context,
                provider,
                agent.model,
            )
            if should_notify:
                from nanobot.bus.events import OutboundMessage

                await bus.publish_outbound(
                    OutboundMessage(
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to,
                        content=response,
                    )
                )
        return response

    cron.on_job = on_cron_job

    # Create channel manager
    channels = ChannelManager(config, bus)

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        # Prefer the most recently updated non-internal session on an enabled channel.
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        # Fallback keeps prior behavior but remains explicit.
        return "cli", "direct"

    # Create heartbeat service
    async def on_heartbeat_execute(tasks: str) -> str:
        """Heartbeat execution for Kosmos task dispatch.

        Important: do NOT call `agent.process_direct(...)` here.
        Doing so allows the model to spawn additional subagents from heartbeat
        instructions, which can violate the one-subagent-at-a-time policy.
        """
        llm_summary = ""

        if nanocats_task_lock.locked():
            return f"{llm_summary}\n\nKosmos heartbeat: task worker is busy.".strip()

        async with nanocats_task_lock:
            pending = await kosmos_tasks.list_pending_tasks()
            in_progress = [t for t in pending if _task_status(t) in {"progress", "in_progress"}]
            qa_tasks = [t for t in pending if _task_status(t) == "qa"]
            release_tasks = [t for t in pending if _task_status(t) == "release"]

            def _assigned_to(task: dict[str, Any]) -> str:
                return str(task.get("assigned_to") or "").strip()

            def _pick_for_role(
                candidates: list[dict[str, Any]], role: str
            ) -> dict[str, Any] | None:
                exact = [t for t in candidates if _assigned_to(t).lower() == role.lower()]
                if exact:
                    return exact[0]
                unassigned = [t for t in candidates if not _assigned_to(t)]
                if unassigned:
                    return unassigned[0]
                return candidates[0] if candidates else None

            if _running_subagent_count() > 0:
                if subagents and hasattr(subagents, "get_spawn_guard_stats"):
                    try:
                        stats = subagents.get_spawn_guard_stats()
                        if int(stats.get("role", 0)) > 0 or int(stats.get("kanban_task", 0)) > 0:
                            logger.info(
                                "Spawn guard stats: role_prevented={} task_prevented={}",
                                stats.get("role", 0),
                                stats.get("kanban_task", 0),
                            )
                    except Exception:
                        logger.exception("Failed to read spawn guard stats")
                if in_progress and _is_role_running(dev_subagent):
                    progress_id = str(in_progress[0].get("id") or "")
                    return (
                        f"{llm_summary}\n\n"
                        f"Kosmos heartbeat: {dev_subagent} already working on task {progress_id}."
                    ).strip()
                if qa_tasks and _is_role_running(qa_subagent):
                    qa_id = str(qa_tasks[0].get("id") or "")
                    return (
                        f"{llm_summary}\n\n"
                        f"Kosmos heartbeat: {qa_subagent} already reviewing task {qa_id}."
                    ).strip()
                if release_tasks and _is_role_running(release_subagent):
                    release_id = str(release_tasks[0].get("id") or "")
                    return (
                        f"{llm_summary}\n\n"
                        f"Kosmos heartbeat: {release_subagent} already releasing task {release_id}."
                    ).strip()
                return f"{llm_summary}\n\nKosmos heartbeat: subagent busy.".strip()

            if in_progress and _is_role_running(dev_subagent):
                progress_id = str(in_progress[0].get("id") or "")
                progress_title = str(in_progress[0].get("title") or "")
                return (
                    f"{llm_summary}\n\n"
                    f"Kosmos heartbeat: {dev_subagent} is still on task {progress_id} ({progress_title})."
                ).strip()

            if in_progress and not _is_role_running(dev_subagent):
                progress_task = _pick_for_role(in_progress, dev_subagent)
                if progress_task:
                    progress_task_id = str(progress_task.get("id") or "")
                    if _is_kanban_task_running(progress_task_id):
                        return (
                            f"{llm_summary}\n\n"
                            f"Kosmos heartbeat: task {progress_task_id} already has an active subagent run."
                        ).strip()

                    progress_path = _resolve_project_path(progress_task)
                    if not (progress_path / "AGENTS.md").exists():
                        _ = await _prepare_todo_task(
                            {
                                **progress_task,
                                "description": str(
                                    progress_task.get("description") or "[resumed task]"
                                ),
                            }
                        )
                        return (
                            f"{llm_summary}\n\n"
                            f"Kosmos heartbeat: prepared missing AGENTS.md/context before resuming {progress_task.get('id')}."
                        ).strip()

                    progress_project_id = str(progress_task.get("project_id") or "")
                    progress_title = str(progress_task.get("title") or "Untitled task")

                    await kosmos_tasks.update_task(
                        progress_task_id,
                        assigned_to=dev_subagent,
                    )

                    progress_instruction = await _build_task_instruction(
                        progress_task, dev_subagent
                    )
                    spawn_tool = agent.tools.get("spawn")
                    if not spawn_tool or not hasattr(spawn_tool, "execute"):
                        return (
                            f"{llm_summary}\n\nKosmos heartbeat: spawn tool unavailable for in-progress task."
                        ).strip()

                    if hasattr(spawn_tool, "set_context"):
                        spawn_tool.set_context("cli", "direct")

                    progress_result = await spawn_tool.execute(
                        task=progress_instruction,
                        label=dev_subagent,
                        task_meta={
                            "kanban_task_id": progress_task_id,
                            "project_id": progress_project_id,
                            "project_name": str(
                                progress_task.get("project_name") or progress_project_id
                            ),
                            "project_path": str(progress_task.get("project_path") or ""),
                            "workspace_path": str(progress_task.get("workspace_path") or ""),
                            "work_branch": str(progress_task.get("work_branch") or ""),
                            "base_branch": str(progress_task.get("base_branch") or ""),
                            "title": progress_title,
                            "subagent_name": dev_subagent,
                        },
                    )
                    return (
                        f"{llm_summary}\n\n"
                        f"Kosmos heartbeat: resumed in-progress task {progress_task_id}. {progress_result}"
                    ).strip()

            if release_tasks and not _is_role_running(release_subagent):
                release_task = _pick_for_role(release_tasks, release_subagent)
                if not release_task:
                    return f"{llm_summary}\n\nKosmos heartbeat: no release task available.".strip()
                release_task_id = str(release_task.get("id") or "")
                if _is_kanban_task_running(release_task_id):
                    return (
                        f"{llm_summary}\n\n"
                        f"Kosmos heartbeat: task {release_task_id} already has an active subagent run."
                    ).strip()
                release_project_id = str(release_task.get("project_id") or "")
                release_title = str(release_task.get("title") or "Untitled task")

                await kosmos_tasks.update_task(
                    release_task_id,
                    assigned_to=release_subagent,
                )

                release_instruction = await _build_task_instruction(release_task, release_subagent)
                spawn_tool = agent.tools.get("spawn")
                if not spawn_tool or not hasattr(spawn_tool, "execute"):
                    return (
                        f"{llm_summary}\n\nKosmos heartbeat: spawn tool unavailable for Release."
                    ).strip()

                if hasattr(spawn_tool, "set_context"):
                    spawn_tool.set_context("cli", "direct")

                release_result = await spawn_tool.execute(
                    task=release_instruction,
                    label=release_subagent,
                    task_meta={
                        "kanban_task_id": release_task_id,
                        "project_id": release_project_id,
                        "project_name": str(release_task.get("project_name") or release_project_id),
                        "project_path": str(release_task.get("project_path") or ""),
                        "workspace_path": str(release_task.get("workspace_path") or ""),
                        "work_branch": str(release_task.get("work_branch") or ""),
                        "base_branch": str(release_task.get("base_branch") or ""),
                        "title": release_title,
                        "subagent_name": release_subagent,
                    },
                )
                return (
                    f"{llm_summary}\n\n"
                    f"Kosmos heartbeat: dispatched release task {release_task_id}. {release_result}"
                ).strip()

            if qa_tasks and not _is_role_running(qa_subagent):
                qa_task = _pick_for_role(qa_tasks, qa_subagent)
                if not qa_task:
                    return f"{llm_summary}\n\nKosmos heartbeat: no QA task available.".strip()
                qa_task_id = str(qa_task.get("id") or "")
                if _is_kanban_task_running(qa_task_id):
                    return (
                        f"{llm_summary}\n\n"
                        f"Kosmos heartbeat: task {qa_task_id} already has an active subagent run."
                    ).strip()
                qa_project_id = str(qa_task.get("project_id") or "")
                qa_title = str(qa_task.get("title") or "Untitled task")

                await kosmos_tasks.update_task(
                    qa_task_id,
                    assigned_to=qa_subagent,
                )

                qa_instruction = await _build_task_instruction(qa_task, qa_subagent)
                spawn_tool = agent.tools.get("spawn")
                if not spawn_tool or not hasattr(spawn_tool, "execute"):
                    return (
                        f"{llm_summary}\n\nKosmos heartbeat: spawn tool unavailable for QA.".strip()
                    )

                if hasattr(spawn_tool, "set_context"):
                    spawn_tool.set_context("cli", "direct")

                qa_result = await spawn_tool.execute(
                    task=qa_instruction,
                    label=qa_subagent,
                    task_meta={
                        "kanban_task_id": qa_task_id,
                        "project_id": qa_project_id,
                        "project_name": str(qa_task.get("project_name") or qa_project_id),
                        "project_path": str(qa_task.get("project_path") or ""),
                        "workspace_path": str(qa_task.get("workspace_path") or ""),
                        "work_branch": str(qa_task.get("work_branch") or ""),
                        "base_branch": str(qa_task.get("base_branch") or ""),
                        "title": qa_title,
                        "subagent_name": qa_subagent,
                    },
                )
                return f"{llm_summary}\n\nKosmos heartbeat: dispatched QA task {qa_task_id}. {qa_result}".strip()

            todo = [t for t in pending if _task_status(t) == "todo"]
            if not todo:
                return f"{llm_summary}\n\nKosmos heartbeat: no pending tasks for {dev_subagent}.".strip()

            if _is_role_running(dev_subagent):
                return f"{llm_summary}\n\nKosmos heartbeat: {dev_subagent} already running.".strip()

            next_task = _pick_for_role(todo, dev_subagent)
            if not next_task:
                return f"{llm_summary}\n\nKosmos heartbeat: no todo task available.".strip()

            ready, prep_message = await _prepare_todo_task(next_task)
            if not ready:
                return f"{llm_summary}\n\n{prep_message}".strip()

            task_id = str(next_task.get("id"))
            if _is_kanban_task_running(task_id):
                return (
                    f"{llm_summary}\n\n"
                    f"Kosmos heartbeat: task {task_id} already has an active subagent run."
                ).strip()
            project_id = str(next_task.get("project_id") or "")
            title = str(next_task.get("title") or "Untitled task")
            claimed = await kosmos_tasks.transition_task(
                task_id,
                to_status="progress",
                comment_text=f"[{dev_subagent}] Claimed task and started implementation.",
                agent_id=dev_subagent,
                agent_name=dev_subagent,
                assigned_to=dev_subagent,
            )
            if not claimed:
                return (
                    f"{llm_summary}\n\n"
                    f"Kosmos heartbeat: could not move task {task_id} to progress (likely 409)."
                ).strip()

            instruction = await _build_task_instruction(next_task, dev_subagent)
            spawn_tool = agent.tools.get("spawn")
            if not spawn_tool or not hasattr(spawn_tool, "execute"):
                return f"{llm_summary}\n\nKosmos heartbeat: spawn tool unavailable.".strip()

            if hasattr(spawn_tool, "set_context"):
                spawn_tool.set_context("cli", "direct")

            result = await spawn_tool.execute(
                task=instruction,
                label=dev_subagent,
                task_meta={
                    "kanban_task_id": task_id,
                    "project_id": project_id,
                    "project_name": str(next_task.get("project_name") or project_id),
                    "project_path": str(next_task.get("project_path") or ""),
                    "workspace_path": str(next_task.get("workspace_path") or ""),
                    "work_branch": str(next_task.get("work_branch") or ""),
                    "base_branch": str(next_task.get("base_branch") or ""),
                    "title": title,
                    "subagent_name": dev_subagent,
                },
            )
            dispatch_info = f"Kosmos heartbeat: dispatched task {task_id}. {result}"
            return f"{llm_summary}\n\n{dispatch_info}".strip()

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel."""
        from nanobot.bus.events import OutboundMessage

        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # No external channel available to deliver to
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
        deliver=hb_cfg.deliver,
        timezone=config.agents.defaults.timezone,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

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

    async def start_kosmos_bg() -> tuple[asyncio.Task | None, Any]:
        try:
            from nanobot.kosmos.server import KosmosServer, parse_kosmos_base_url

            host, kosmos_port = parse_kosmos_base_url(kosmos_api_url)
            kosmos_server = KosmosServer(host=host, port=kosmos_port)
            kosmos_task = asyncio.create_task(kosmos_server.start(), name="kosmos-server")
            await asyncio.sleep(0.2)
            if kosmos_task.done():
                exc = kosmos_task.exception()
                if exc:
                    raise exc
            console.print(
                f"[green]✓[/green] Kosmos API: http://{host}:{kosmos_port} & ws://{host}:{kosmos_port + 1}"
            )
            return kosmos_task, kosmos_server
        except Exception as e:
            error_msg = f"Kosmos failed to start: {e}"
            if "No module named" in str(e):
                error_msg += "\n  → Missing dependency. Run: pip install aiosqlite"
            console.print(f"[red]✘ ERROR: {error_msg}[/red]")
            raise SystemExit(1)

    # Register Dream system job (always-on, idempotent on restart)
    dream_cfg = config.agents.defaults.dream
    if dream_cfg.model_override:
        agent.dream.model = dream_cfg.model_override
    agent.dream.max_batch_size = dream_cfg.max_batch_size
    agent.dream.max_iterations = dream_cfg.max_iterations
    from nanobot.cron.types import CronPayload

    cron.register_system_job(
        CronJob(
            id="dream",
            name="dream",
            schedule=dream_cfg.build_schedule(config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        )
    )
    console.print(f"[green]✓[/green] Dream: {dream_cfg.describe_schedule()}")

    removed_legacy_jobs = _remove_legacy_task_checker_jobs()
    if removed_legacy_jobs:
        console.print(
            f"[yellow]✓[/yellow] Removed {removed_legacy_jobs} legacy task-checker cron job(s)"
        )

    checker_interval_s = max(30, min(60, int(hb_cfg.interval_s)))
    checker_job = CronJob(
        id="kosmos-task-checker",
        name="kosmos-task-checker",
        enabled=True,
        schedule=CronSchedule(kind="every", every_ms=checker_interval_s * 1000),
        payload=CronPayload(
            kind="system_event",
            message="Kosmos task checker (heartbeat preflight dispatcher)",
        ),
    )
    cron.register_system_job(checker_job)
    console.print(
        f"[green]✓[/green] Kosmos Task Checker: every {checker_interval_s}s (preflight enforced)"
    )

    async def run():
        kosmos_task: asyncio.Task | None = None
        kosmos_server = None
        try:
            kosmos_task, kosmos_server = await start_kosmos_bg()
            await cron.start()
            await heartbeat.start()

            # Run one checker cycle immediately on startup so users don't need
            # to wait for the first full cron interval.
            try:
                startup_result = await on_heartbeat_execute("")
                logger.info("Kosmos startup checker executed: {}", startup_result)
            except Exception:
                logger.exception("Kosmos startup checker failed")

            await asyncio.gather(
                agent.run(),
                channels.start_all(),
                _health_server(config.gateway.host, port),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback

            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
            if kosmos_task:
                kosmos_task.cancel()
                with suppress(asyncio.CancelledError):
                    await kosmos_task
            if kosmos_server:
                with suppress(Exception):
                    await kosmos_server.close_db()
            events_listener.cancel()
            with suppress(asyncio.CancelledError):
                await events_listener

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
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Render assistant output as Markdown"
    ),
    logs: bool = typer.Option(
        False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"
    ),
):
    """Interact with the agent directly."""
    from loguru import logger

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService

    config = _load_runtime_config(config, workspace)
    sync_workspace_templates(config.workspace_path)

    bus = MessageBus()
    provider = _make_provider(config)

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

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_config=config.tools.web,
        context_block_limit=config.agents.defaults.context_block_limit,
        max_tool_result_chars=config.agents.defaults.max_tool_result_chars,
        provider_retry_mode=config.agents.defaults.provider_retry_mode,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
        unified_session=config.agents.defaults.unified_session,
        disabled_skills=config.agents.defaults.disabled_skills,
        session_ttl_minutes=config.agents.defaults.session_ttl_minutes,
    )
    restart_notice = consume_restart_notice_from_env()
    if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
        _print_agent_response(
            format_restart_completed_message(restart_notice.started_at_raw),
            render_markdown=False,
        )

    # Shared reference for progress callbacks
    _thinking: ThinkingSpinner | None = None

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        _print_cli_progress_line(content, _thinking)

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            renderer = StreamRenderer(render_markdown=markdown)
            response = await agent_loop.process_direct(
                message,
                session_id,
                on_progress=_cli_progress,
                on_stream=renderer.on_delta,
                on_stream_end=renderer.on_end,
            )
            if not renderer.streamed:
                await renderer.close()
                _print_agent_response(
                    response.content if response else "",
                    render_markdown=markdown,
                    metadata=response.metadata if response else None,
                )
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from nanobot.bus.events import InboundMessage

        _init_prompt_session()
        console.print(
            f"{__logo__} Interactive mode [bold blue]({config.agents.defaults.model})[/bold blue] — type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n"
        )
        console.print(
            f"{__logo__} Interactive mode [bold blue]({config.agents.defaults.model})[/bold blue] — type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n"
        )

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
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, "SIGPIPE"):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive():
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[tuple[str, dict]] = []
            renderer: StreamRenderer | None = None

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

                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                await _print_interactive_progress_line(msg.content, _thinking)
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
                        renderer = StreamRenderer(render_markdown=markdown)

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
                            content, meta = turn_response[0]
                            if content and not meta.get("_streamed"):
                                if renderer:
                                    await renderer.close()
                                _print_agent_response(
                                    content,
                                    render_markdown=markdown,
                                    metadata=meta,
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


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    from nanobot.config.paths import get_bridge_install_dir

    user_bridge = get_bridge_install_dir()

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    npm_path = shutil.which("npm")
    if not npm_path:
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # nanobot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run([npm_path, "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run([npm_path, "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login(
    channel_name: str = typer.Argument(..., help="Channel name (e.g. weixin, whatsapp)"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force re-authentication even if already logged in"
    ),
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


@app.command("approve-release")
def approve_release(
    task_id: str = typer.Argument(..., help="Task ID in release stage"),
    branch: str = typer.Option(..., "--branch", help="Approved branch for commit/push"),
    push: bool = typer.Option(False, "--push/--no-push", help="Whether push is approved"),
    approved_by: str = typer.Option("human", "--approved-by", help="Approver identity"),
    comment: str = typer.Option(
        "", "--comment", help="Optional approval comment stored in task comments"
    ),
    api_url: str | None = typer.Option(None, "--api-url", help="Kosmos API base URL"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Approve a release task so Rydia can move it to done."""
    from nanobot.services.kosmos_tasks import KosmosTasksClient

    runtime_config = _load_runtime_config(config, workspace=None)
    resolved_api_url = str(api_url or runtime_config.gateway.kosmos_api_url).strip()
    client = KosmosTasksClient(base_url=resolved_api_url)

    async def _run() -> tuple[dict[str, Any] | None, str]:
        task = await client.get_task(task_id)
        if not task:
            return None, f"Task {task_id} not found"

        workspace_path = str(task.get("workspace_path") or "").strip()
        work_branch = str(task.get("work_branch") or "").strip()
        selected_branch = branch.strip() or work_branch
        if not selected_branch:
            return None, "No branch available to approve release"

        if not workspace_path:
            return None, "Task has no workspace_path; cannot run release git steps"

        ws = Path(workspace_path)
        if not ws.exists() or not ws.is_dir():
            return None, f"Workspace path not found: {workspace_path}"

        def _git(args: list[str]) -> tuple[int, str, str]:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(ws),
                capture_output=True,
                text=True,
            )
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

        code, current_branch, err = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0:
            return None, f"Failed to detect current branch in workspace: {err}"

        if current_branch != selected_branch:
            checkout_code, _, checkout_err = _git(["checkout", selected_branch])
            if checkout_code != 0:
                create_code, _, create_err = _git(["checkout", "-b", selected_branch])
                if create_code != 0:
                    return None, (
                        f"Failed to checkout/create branch {selected_branch}: "
                        f"{checkout_err or create_err}"
                    )

        status_code, status_out, status_err = _git(["status", "--porcelain"])
        if status_code != 0:
            return None, f"Failed to inspect git status: {status_err}"

        if status_out.strip():
            add_code, _, add_err = _git(["add", "-A"])
            if add_code != 0:
                return None, f"Failed to stage changes: {add_err}"

            commit_message = f"release: finalize task {task_id}"
            commit_code, commit_out, commit_err = _git(["commit", "-m", commit_message])
            if commit_code != 0:
                return None, f"Failed to create commit: {commit_err or commit_out}"

        if push:
            push_code, push_out, push_err = _git(["push", "-u", "origin", selected_branch])
            if push_code != 0:
                return None, f"Failed to push branch {selected_branch}: {push_err or push_out}"

        approved = await client.approve_release(
            task_id,
            approved_by=approved_by,
            branch=selected_branch,
            push=push,
            comment_text=comment.strip() or None,
        )
        if not approved:
            return None, f"Failed to approve release for task {task_id}"

        moved = await client.transition_task(
            task_id,
            to_status="done",
            comment_text=(
                f"Release approved by {approved_by}. "
                f"Branch={selected_branch}, push={'yes' if push else 'no'}. "
                "Task moved to done."
            ),
            agent_id="Kosmos",
            agent_name="Kosmos",
            assigned_to=str(task.get("assigned_to") or "Rydia"),
        )
        if not moved:
            return None, (f"Release approved but failed to transition task {task_id} to done.")

        return moved, selected_branch

    result, branch_used_or_error = asyncio.run(_run())
    if not result:
        console.print(
            f"[red]✗ Release approval failed for task {task_id}[/red] "
            f"[dim](api={resolved_api_url})[/dim]\n{branch_used_or_error}"
        )
        raise typer.Exit(1)

    console.print(
        f"[green]✓ Release approved[/green] task={task_id} "
        f"branch={branch_used_or_error} push={'yes' if push else 'no'} by={approved_by} -> done"
    )


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(
        f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")

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
                console.print(
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                )


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn
        return fn

    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(
        ..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"
    ),
):
    """Authenticate with an OAuth provider."""
    from nanobot.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive

        token = None
        try:
            token = get_token()
        except Exception:
            pass
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(
            f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]"
        )
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


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
