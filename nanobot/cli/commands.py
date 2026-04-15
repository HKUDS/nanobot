"""CLI commands for nanobot."""

import asyncio
import os
import select
import signal
import sys
from contextlib import nullcontext
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


class SafeFileHistory(FileHistory):
    """FileHistory subclass that sanitizes surrogate characters on write.

    On Windows, special Unicode input (emoji, mixed-script) can produce
    surrogate characters that crash prompt_toolkit's file write.
    See issue #2846.
    """

    def store_string(self, string: str) -> None:
        safe = string.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
        super().store_string(safe)


from nanobot.cli.stream import StreamRenderer, ThinkingSpinner
from nanobot.config.paths import get_workspace_path, is_default_workspace
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates
from nanobot.utils.restart import (
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)

app = typer.Typer(
    name="nanobot",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
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
def gateway(
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
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.services.nanocats_tasks import NanoCatsTasksClient
    from nanobot.session.manager import SessionManager

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

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

    # Register NanoCats agent hook for real-time events
    from nanobot.agent.hooks import create_nanocats_hook

    nanocats_hook = create_nanocats_hook(workspace=config.workspace_path)
    agent._extra_hooks.append(nanocats_hook)

    nanocats_tasks = NanoCatsTasksClient(base_url="http://localhost:18794")
    nanocats_task_lock = asyncio.Lock()
    active_subagent_roles: set[str] = set()
    DEV_SUBAGENT = "Vicks"
    QA_SUBAGENT = "Wedge"
    RELEASE_SUBAGENT = "Rydia"

    def _task_status(task: dict[str, Any]) -> str:
        return str(task.get("status") or "").strip().lower()

    async def _build_task_instruction(task: dict[str, Any], role: str) -> str:
        project_id = task.get("project_id") or ""
        title = task.get("title") or "Untitled task"
        description = task.get("description") or ""
        status = str(task.get("status") or "").strip().lower()
        project_path = (
            str(Path.home() / "proyectos" / str(project_id))
            if project_id
            else str(config.workspace_path)
        )
        role_instruction = (
            "You are Vicks (developer). Implement/fix the task and leave it ready for QA."
            if role == DEV_SUBAGENT
            else (
                "You are Wedge (code reviewer / QA). Validate implementation, run checks, and approve or report issues."
                if role == QA_SUBAGENT
                else (
                    "You are Rydia (release lead). Prepare the final handoff summary and propose conventional commits. "
                    "Do not run git commit or git push until explicit human approval is provided with branch details."
                )
            )
        )
        return (
            f"Resolve NanoCats task {task.get('id')} for project '{project_id}' as {role}.\n"
            f"Title: {title}\n"
            f"Description: {description}\n"
            f"Current Kanban status: {status or 'todo'}\n"
            f"Workspace: {project_path}\n"
            "Requirements:\n"
            f"- {role_instruction}\n"
            "- Do the implementation work needed to complete this task.\n"
            "- Run relevant checks/tests when applicable.\n"
            "- Return a concise completion report with what changed and verification status."
        )

    async def _on_subagent_task_complete(payload: dict[str, Any]) -> None:
        task_meta = payload.get("task_meta") or {}
        kanban_task_id = task_meta.get("kanban_task_id")
        if not kanban_task_id:
            return
        status = payload.get("status")
        role = str(task_meta.get("subagent_name") or "")
        active_subagent_roles.discard(role)
        runtime_subagent_id = str(payload.get("subagent_runtime_id") or "")
        reviewer = runtime_subagent_id if runtime_subagent_id else role or "nanobot"
        result_preview = str(payload.get("result") or "")
        headline = "Completed successfully" if status == "ok" else "Failed / needs follow-up"
        role_label = role or "Subagent"
        body = (
            result_preview[:900].strip() if result_preview else "No detailed output was produced."
        )
        comment_text = f"[{role_label}] {headline}\n\n{body}"

        # Ensure identities exist for backend ACL checks on comments.
        if runtime_subagent_id:
            await nanocats_tasks.upsert_agent_identity(
                agent_id=runtime_subagent_id,
                agent_name=role or runtime_subagent_id,
                project_id=str(task_meta.get("project_id") or ""),
                status="coding" if role == DEV_SUBAGENT else "consulting",
                mood="focused",
                current_task=str(task_meta.get("title") or "Task"),
            )
        if role in {DEV_SUBAGENT, QA_SUBAGENT, RELEASE_SUBAGENT}:
            await nanocats_tasks.upsert_agent_identity(
                agent_id=role,
                agent_name=role,
                project_id=str(task_meta.get("project_id") or ""),
                status="coding" if role == DEV_SUBAGENT else "consulting",
                mood="focused",
                current_task=str(task_meta.get("title") or "Task"),
            )

        async def _ensure_assigned_to(expected_name: str) -> bool:
            task_snapshot = await nanocats_tasks.get_task(str(kanban_task_id))
            if not task_snapshot:
                logger.warning("Task {} not found before comment", kanban_task_id)
                return False
            current_assigned = str(task_snapshot.get("assigned_to") or "").strip()
            if current_assigned.lower() != expected_name.lower():
                updated = await nanocats_tasks.update_task(
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
            role if role in {DEV_SUBAGENT, QA_SUBAGENT, RELEASE_SUBAGENT} else reviewer
        )
        owner_ok = await _ensure_assigned_to(expected_owner_for_comment)
        if not owner_ok:
            logger.warning(
                "Task {} completion skipped because owner check failed for {}",
                kanban_task_id,
                expected_owner_for_comment,
            )
            return

        created_comment = await nanocats_tasks.create_task_comment(
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
            if role == DEV_SUBAGENT:
                transition = "in progress -> qa"
                await nanocats_tasks.transition_task(
                    kanban_task_id,
                    to_status="qa",
                    comment_text=f"[{role}] Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to=QA_SUBAGENT,
                )
            elif role == QA_SUBAGENT:
                transition = "qa -> release"
                await nanocats_tasks.transition_task(
                    kanban_task_id,
                    to_status="release",
                    comment_text=f"[{role}] Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to=RELEASE_SUBAGENT,
                )
            else:
                task_snapshot = await nanocats_tasks.get_task(str(kanban_task_id))
                approved = bool((task_snapshot or {}).get("release_approved"))
                if approved:
                    transition = "release -> done"
                    await nanocats_tasks.transition_task(
                        kanban_task_id,
                        to_status="done",
                        comment_text=f"[{role}] Transition: {transition}\n\n{body}",
                        agent_id=role,
                        agent_name=role,
                        assigned_to=RELEASE_SUBAGENT,
                    )
                else:
                    transition = "release -> release (awaiting human approval)"
                    await nanocats_tasks.update_task(
                        kanban_task_id,
                        assigned_to=RELEASE_SUBAGENT,
                    )
                    await nanocats_tasks.create_task_comment(
                        task_id=str(kanban_task_id),
                        agent_id=RELEASE_SUBAGENT,
                        comment=(
                            "[Rydia] Release prepared. Waiting for explicit human approval "
                            "(approved_by, branch, push) before moving to done.\n\n"
                            f"{body}"
                        ),
                    )
        else:
            if role == DEV_SUBAGENT:
                transition = "in progress -> todo"
                await nanocats_tasks.transition_task(
                    kanban_task_id,
                    to_status="todo",
                    comment_text=f"[{role}] Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to="",
                )
            elif role == QA_SUBAGENT:
                transition = "qa -> todo"
                await nanocats_tasks.transition_task(
                    kanban_task_id,
                    to_status="todo",
                    comment_text=f"[{role}] Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to="",
                )
            else:
                transition = "release -> todo"
                await nanocats_tasks.transition_task(
                    kanban_task_id,
                    to_status="todo",
                    comment_text=f"[{role}] Transition: {transition}\n\n{body}",
                    agent_id=role,
                    agent_name=role,
                    assigned_to="",
                )

        # Keep assignment aligned with role name for backend ACL on comments.
        if role in {DEV_SUBAGENT, QA_SUBAGENT, RELEASE_SUBAGENT}:
            await nanocats_tasks.update_task(
                kanban_task_id,
                assigned_to=role,
            )

            owner_ok = await _ensure_assigned_to(role)
            if not owner_ok:
                logger.warning(
                    "Task {} transition comment skipped because owner check failed for role {}",
                    kanban_task_id,
                    role,
                )
                return

            transition_comment = f"[{role}] Handoff note: {transition}\n\n{body}"
            transition_comment_created = await nanocats_tasks.create_task_comment(
                task_id=str(kanban_task_id),
                agent_id=role,
                comment=transition_comment,
            )
            if not transition_comment_created:
                logger.warning(
                    "Task {} transition comment missing for role {} ({})",
                    kanban_task_id,
                    role,
                    transition,
                )

        project_id = str(task_meta.get("project_id") or "")
        title = str(task_meta.get("title") or "Task")
        if status == "ok":
            done_status = "consulting"
            done_message = (
                f"{title} - {transition}" if role == DEV_SUBAGENT else f"{title} - {transition}"
            )
        else:
            done_status = "error"
            done_message = (
                f"{title} - {transition}" if role == DEV_SUBAGENT else f"{title} - {transition}"
            )
        from nanobot.services.nanocats import get_nanocats

        nanocats = get_nanocats()
        if nanocats and nanocats._running:
            await nanocats.send_activity(
                {
                    "id": f"task-end-{kanban_task_id}",
                    "agentId": payload.get("task_id", "main"),
                    "agentName": payload.get("label", "Subagent"),
                    "projectId": project_id,
                    "type": "status",
                    "status": done_status,
                    "currentTask": done_message,
                    "mood": "focused" if status == "ok" else "tired",
                    "message": done_message,
                }
            )

    async def _on_subagent_task_start(payload: dict[str, Any]) -> None:
        task_meta = payload.get("task_meta") or {}
        kanban_task_id = task_meta.get("kanban_task_id")
        if not kanban_task_id:
            return
        role = str(task_meta.get("subagent_name") or "")
        if role:
            active_subagent_roles.add(role)

        # Keep the task owner aligned with the running subagent.
        await nanocats_tasks.update_task(
            kanban_task_id,
            assigned_to=role or str(payload.get("task_id") or "nanobot"),
        )

        target_status = (
            "progress" if role == DEV_SUBAGENT else ("qa" if role == QA_SUBAGENT else "release")
        )
        await nanocats_tasks.transition_task(
            kanban_task_id,
            to_status=target_status,
            comment_text=f"[{role}] Started work in {target_status}.",
            agent_id=role or str(payload.get("task_id") or "nanobot"),
            agent_name=role or str(payload.get("label") or "nanobot"),
            assigned_to=role or str(payload.get("task_id") or "nanobot"),
        )

        project_id = str(task_meta.get("project_id") or "")
        title = str(task_meta.get("title") or "Working on task")
        from nanobot.services.nanocats import get_nanocats

        nanocats = get_nanocats()
        if nanocats and nanocats._running:
            await nanocats.send_activity(
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

    agent.subagents.set_on_task_start(_on_subagent_task_start)
    agent.subagents.set_on_task_complete(_on_subagent_task_complete)

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        # Dream is an internal job — run directly, not through the agent loop.
        if job.name == "dream":
            try:
                await agent.dream.run()
                logger.info("Dream cron job completed")
            except Exception:
                logger.exception("Dream cron job failed")
            return None

        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.message import MessageTool
        from nanobot.utils.evaluator import evaluate_response

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            resp = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        response = resp.content if resp else ""

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            should_notify = await evaluate_response(
                response,
                reminder_note,
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
        """Heartbeat execution for NanoCats task dispatch.

        Important: do NOT call `agent.process_direct(...)` here.
        Doing so allows the model to spawn additional subagents from heartbeat
        instructions, which can violate the one-subagent-at-a-time policy.
        """
        llm_summary = ""

        if nanocats_task_lock.locked():
            return f"{llm_summary}\n\nNanoCats heartbeat: task worker is busy.".strip()

        async with nanocats_task_lock:
            pending = await nanocats_tasks.list_pending_tasks()
            in_progress = [t for t in pending if _task_status(t) in {"progress", "in_progress"}]
            qa_tasks = [t for t in pending if _task_status(t) == "qa"]
            release_tasks = [t for t in pending if _task_status(t) == "release"]

            if agent.subagents.get_running_count() > 0:
                if in_progress and DEV_SUBAGENT in active_subagent_roles:
                    progress_id = str(in_progress[0].get("id") or "")
                    return (
                        f"{llm_summary}\n\n"
                        f"NanoCats heartbeat: {DEV_SUBAGENT} already working on task {progress_id}."
                    ).strip()
                if qa_tasks and QA_SUBAGENT in active_subagent_roles:
                    qa_id = str(qa_tasks[0].get("id") or "")
                    return (
                        f"{llm_summary}\n\n"
                        f"NanoCats heartbeat: {QA_SUBAGENT} already reviewing task {qa_id}."
                    ).strip()
                if release_tasks and RELEASE_SUBAGENT in active_subagent_roles:
                    release_id = str(release_tasks[0].get("id") or "")
                    return (
                        f"{llm_summary}\n\n"
                        f"NanoCats heartbeat: {RELEASE_SUBAGENT} already releasing task {release_id}."
                    ).strip()
                return f"{llm_summary}\n\nNanoCats heartbeat: subagent busy.".strip()

            if in_progress and DEV_SUBAGENT in active_subagent_roles:
                progress_id = str(in_progress[0].get("id") or "")
                progress_title = str(in_progress[0].get("title") or "")
                return (
                    f"{llm_summary}\n\n"
                    f"NanoCats heartbeat: {DEV_SUBAGENT} is still on task {progress_id} ({progress_title})."
                ).strip()

            if release_tasks and RELEASE_SUBAGENT not in active_subagent_roles:
                release_task = release_tasks[0]
                release_task_id = str(release_task.get("id") or "")
                release_project_id = str(release_task.get("project_id") or "")
                release_title = str(release_task.get("title") or "Untitled task")

                await nanocats_tasks.update_task(
                    release_task_id,
                    assigned_to=RELEASE_SUBAGENT,
                )

                release_instruction = await _build_task_instruction(release_task, RELEASE_SUBAGENT)
                spawn_tool = agent.tools.get("spawn")
                if not spawn_tool or not hasattr(spawn_tool, "execute"):
                    return (
                        f"{llm_summary}\n\nNanoCats heartbeat: spawn tool unavailable for Release."
                    ).strip()

                if hasattr(spawn_tool, "set_context"):
                    spawn_tool.set_context("cli", "direct")

                release_result = await spawn_tool.execute(
                    task=release_instruction,
                    label=RELEASE_SUBAGENT,
                    task_meta={
                        "kanban_task_id": release_task_id,
                        "project_id": release_project_id,
                        "title": release_title,
                        "subagent_name": RELEASE_SUBAGENT,
                    },
                )
                return (
                    f"{llm_summary}\n\n"
                    f"NanoCats heartbeat: dispatched release task {release_task_id}. {release_result}"
                ).strip()

            if qa_tasks and QA_SUBAGENT not in active_subagent_roles:
                qa_task = qa_tasks[0]
                qa_task_id = str(qa_task.get("id") or "")
                qa_project_id = str(qa_task.get("project_id") or "")
                qa_title = str(qa_task.get("title") or "Untitled task")

                await nanocats_tasks.update_task(
                    qa_task_id,
                    assigned_to=QA_SUBAGENT,
                )

                qa_instruction = await _build_task_instruction(qa_task, QA_SUBAGENT)
                spawn_tool = agent.tools.get("spawn")
                if not spawn_tool or not hasattr(spawn_tool, "execute"):
                    return f"{llm_summary}\n\nNanoCats heartbeat: spawn tool unavailable for QA.".strip()

                if hasattr(spawn_tool, "set_context"):
                    spawn_tool.set_context("cli", "direct")

                qa_result = await spawn_tool.execute(
                    task=qa_instruction,
                    label=QA_SUBAGENT,
                    task_meta={
                        "kanban_task_id": qa_task_id,
                        "project_id": qa_project_id,
                        "title": qa_title,
                        "subagent_name": QA_SUBAGENT,
                    },
                )
                return f"{llm_summary}\n\nNanoCats heartbeat: dispatched QA task {qa_task_id}. {qa_result}".strip()

            todo = [t for t in pending if _task_status(t) == "todo"]
            if not todo:
                return f"{llm_summary}\n\nNanoCats heartbeat: no pending tasks for {DEV_SUBAGENT}.".strip()

            if DEV_SUBAGENT in active_subagent_roles:
                return (
                    f"{llm_summary}\n\nNanoCats heartbeat: {DEV_SUBAGENT} already running.".strip()
                )

            next_task = todo[0]
            task_id = str(next_task.get("id"))
            project_id = str(next_task.get("project_id") or "")
            title = str(next_task.get("title") or "Untitled task")
            claimed = await nanocats_tasks.transition_task(
                task_id,
                to_status="progress",
                comment_text=f"[{DEV_SUBAGENT}] Claimed task and started implementation.",
                agent_id=DEV_SUBAGENT,
                agent_name=DEV_SUBAGENT,
                assigned_to=DEV_SUBAGENT,
            )
            if not claimed:
                return (
                    f"{llm_summary}\n\n"
                    f"NanoCats heartbeat: could not move task {task_id} to progress (likely 409)."
                ).strip()

            instruction = await _build_task_instruction(next_task, DEV_SUBAGENT)
            spawn_tool = agent.tools.get("spawn")
            if not spawn_tool or not hasattr(spawn_tool, "execute"):
                return f"{llm_summary}\n\nNanoCats heartbeat: spawn tool unavailable.".strip()

            if hasattr(spawn_tool, "set_context"):
                spawn_tool.set_context("cli", "direct")

            result = await spawn_tool.execute(
                task=instruction,
                label=DEV_SUBAGENT,
                task_meta={
                    "kanban_task_id": task_id,
                    "project_id": project_id,
                    "title": title,
                    "subagent_name": DEV_SUBAGENT,
                },
            )
            dispatch_info = f"NanoCats heartbeat: dispatched task {task_id}. {result}"
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

    # Start NanoCats service for agent monitoring (inside async run)
    async def start_nanocats_bg():
        try:
            from nanobot.services.nanocats import start_nanocats

            await start_nanocats()
            console.print(f"[green]✓[/green] NanoCats: ws://0.0.0.0:18791 & http://0.0.0.0:18792")
        except Exception as e:
            console.print(f"[yellow]Warning: NanoCats failed to start: {e}[/yellow]")

    # Register Dream system job (always-on, idempotent on restart)
    dream_cfg = config.agents.defaults.dream
    if dream_cfg.model_override:
        agent.dream.model = dream_cfg.model_override
    agent.dream.max_batch_size = dream_cfg.max_batch_size
    agent.dream.max_iterations = dream_cfg.max_iterations
    from nanobot.cron.types import CronJob, CronPayload

    cron.register_system_job(
        CronJob(
            id="dream",
            name="dream",
            schedule=dream_cfg.build_schedule(config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        )
    )
    console.print(f"[green]✓[/green] Dream: {dream_cfg.describe_schedule()}")

    async def run():
        try:
            await start_nanocats_bg()
            await cron.start()
            await heartbeat.start()
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
            # Stop NanoCats
            try:
                from nanobot.services.nanocats import get_nanocats

                nanocats = get_nanocats()
                if nanocats:
                    await nanocats.stop()
            except Exception:
                pass

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
    api_url: str = typer.Option(
        "http://localhost:18794", "--api-url", help="NanoCats API base URL"
    ),
):
    """Approve a release task so Rydia can move it to done."""
    from nanobot.services.nanocats_tasks import NanoCatsTasksClient

    client = NanoCatsTasksClient(base_url=api_url)

    async def _run() -> dict[str, Any] | None:
        return await client.approve_release(
            task_id,
            approved_by=approved_by,
            branch=branch,
            push=push,
            comment_text=comment.strip() or None,
        )

    result = asyncio.run(_run())
    if not result:
        console.print(
            f"[red]✗ Failed to approve release for task {task_id}[/red] [dim](api={api_url})[/dim]"
        )
        raise typer.Exit(1)

    console.print(
        f"[green]✓ Release approved[/green] task={task_id} "
        f"branch={branch} push={'yes' if push else 'no'} by={approved_by}"
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
