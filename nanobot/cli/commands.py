"""CLI commands for nanobot."""

import asyncio
import json
import os
import re
import select
import shutil
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
        try:
            if sys.stdout.isatty():
                # Restore a visible cursor even if prompt_toolkit exited mid-render.
                sys.stdout.write("\x1b[?25h\x1b[0m")
                sys.stdout.flush()
        except Exception:
            pass
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass
    try:
        if sys.stdout.isatty():
            # Make sure the cursor is visible and text attributes are reset.
            sys.stdout.write("\x1b[?25h\x1b[0m")
            sys.stdout.flush()
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
    if not text.strip():
        return
    with thinking.pause() if thinking else nullcontext():
        console.print(f"  [dim]↳ {text}[/dim]")


async def _print_interactive_progress_line(text: str, thinking: ThinkingSpinner | None) -> None:
    """Print an interactive progress line, pausing the spinner if needed."""
    if not text.strip():
        return
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


def _get_agenthifive_skill_source() -> Path:
    """Return the bundled AgentHiFive skill directory."""
    return Path(__file__).resolve().parents[2] / "skills" / "agenthifive"


def _build_agenthifive_mcp_defaults(
    *,
    mcp_command: str,
    mcp_path: str | None,
    base_url: str,
    download_dir: str | None,
    agent_id: str | None,
    private_key_path: str | None,
    private_key: str | None,
    token_audience: str | None,
    bearer_token: str | None,
) -> dict[str, Any]:
    """Build the default MCP server config for AgentHiFive."""
    if mcp_path:
        command = "node"
        args = [mcp_path]
    else:
        command = mcp_command
        args = []

    env = {"AGENTHIFIVE_BASE_URL": base_url}
    if download_dir:
        env["AGENTHIFIVE_DOWNLOAD_DIR"] = download_dir
    if bearer_token:
        env["AGENTHIFIVE_BEARER_TOKEN"] = bearer_token
    else:
        if agent_id:
            env["AGENTHIFIVE_AGENT_ID"] = agent_id
        if private_key_path:
            env["AGENTHIFIVE_PRIVATE_KEY_PATH"] = private_key_path
        if private_key:
            env["AGENTHIFIVE_PRIVATE_KEY"] = private_key
        if token_audience:
            env["AGENTHIFIVE_TOKEN_AUDIENCE"] = token_audience

    return {
        "type": "stdio",
        "command": command,
        "args": args,
        "env": env,
        "toolTimeout": 30,
        "enabledTools": ["*"],
    }


_ENV_PLACEHOLDER_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _agenthifive_placeholder_env_name(value: str | None) -> str | None:
    """Return the referenced env var for a ${NAME} placeholder."""
    if not value:
        return None

    match = _ENV_PLACEHOLDER_PATTERN.fullmatch(value.strip())
    return match.group(1) if match else None


def _agenthifive_has_configured_value(value: str | None) -> bool:
    """Whether a setup value is already available literally or via env placeholder."""
    if value is None:
        return False

    env_name = _agenthifive_placeholder_env_name(value)
    if env_name:
        return bool(os.environ.get(env_name))

    return bool(value.strip())


def _prompt_agenthifive_value(
    prompt_text: str,
    *,
    hide_input: bool = False,
    default: str | None = None,
) -> str:
    """Prompt until a non-empty value is provided."""
    while True:
        resolved = typer.prompt(
            prompt_text,
            hide_input=hide_input,
            default=default,
            show_default=default is not None,
        ).strip()
        if resolved:
            return resolved
        console.print("[yellow]Value cannot be empty.[/yellow]")


def _resolve_agenthifive_setup_value(
    value: str | None,
    *,
    prompt_text: str,
    hide_input: bool = False,
    prompt_default: str | None = None,
) -> str | None:
    """Resolve a setup value, prompting only when an env placeholder is unset."""
    if value is None:
        return None

    env_name = _agenthifive_placeholder_env_name(value)
    if not env_name:
        return value

    if os.environ.get(env_name):
        return value

    return _prompt_agenthifive_value(
        prompt_text,
        hide_input=hide_input,
        default=prompt_default,
    )


def _generate_agenthifive_jwk_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate a fresh ES256 JWK pair for AgentHiFive agent auth."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from jwt.algorithms import ECAlgorithm

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_jwk = json.loads(ECAlgorithm.to_jwk(private_key))
    public_jwk = json.loads(ECAlgorithm.to_jwk(private_key.public_key()))
    return private_jwk, public_jwk


def _bootstrap_agenthifive_public_key(
    *,
    base_url: str,
    bootstrap_secret: str,
    public_key: dict[str, Any],
) -> str:
    """Register a public key with AgentHiFive and return the assigned agent ID."""
    import httpx

    base_url = base_url.strip().rstrip("/")
    try:
        response = httpx.post(
            f"{base_url}/v1/agents/bootstrap",
            json={"bootstrapSecret": bootstrap_secret, "publicKey": public_key},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or exc.response.reason_phrase
        raise RuntimeError(
            f"AgentHiFive bootstrap failed: {exc.response.status_code} {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"AgentHiFive bootstrap request failed: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("AgentHiFive bootstrap returned invalid JSON") from exc

    agent_id = str(body.get("agentId", "")).strip()
    if not agent_id:
        raise RuntimeError("AgentHiFive bootstrap response did not include agentId")
    return agent_id


def _prepare_agenthifive_bootstrap_key_path(
    value: str | None,
    *,
    force: bool,
) -> str:
    """Resolve where the generated private JWK should be saved."""
    default_path = "~/.nanobot/agenthifive-agent.jwk"
    candidate = value

    while True:
        resolved = (
            _resolve_agenthifive_setup_value(
                candidate,
                prompt_text="Path to save the AgentHiFive private JWK",
                prompt_default=default_path,
            )
            or default_path
        )
        expanded = Path(resolved).expanduser()
        if force or not expanded.exists():
            return str(expanded)
        if typer.confirm(
            f"Private JWK already exists at {expanded}. Overwrite it?",
            default=False,
        ):
            return str(expanded)
        candidate = None


def _write_agenthifive_private_jwk(path_value: str, private_jwk: dict[str, Any]) -> None:
    """Persist the generated private JWK locally with restrictive permissions."""
    target = Path(path_value).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(private_jwk, indent=2), encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass


def _run_setup_channels(
    *,
    config_path: Path,
    channel_name: str | None = None,
) -> None:
    """Run the existing channel configuration UI and save changes if any."""
    from nanobot.cli import onboard
    from nanobot.config.loader import load_config, save_config, set_config_path

    resolved_config_path = config_path.expanduser().resolve()
    set_config_path(resolved_config_path)
    config = load_config(resolved_config_path)
    original_dump = config.model_dump(by_alias=True)

    try:
        onboard._get_questionary()
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print(
            "Install project dependencies and rerun [cyan]nanobot setup-agenthifive[/cyan] "
            "or [cyan]nanobot onboard --wizard[/cyan]."
        )
        raise typer.Exit(1) from exc

    if channel_name:
        channels = onboard._get_channel_names()
        if channel_name not in channels:
            available = ", ".join(sorted(channels))
            console.print(f"[red]Unknown channel:[/red] {channel_name}")
            console.print(f"Available channels: {available}")
            raise typer.Exit(1)
        onboard._configure_channel(config, channel_name)
    else:
        onboard._configure_channels(config)

    if config.model_dump(by_alias=True) != original_dump:
        save_config(config, resolved_config_path)
        console.print(f"[green]✓[/green] Saved channel configuration to {resolved_config_path}")
    else:
        console.print("[dim]No channel changes were saved.[/dim]")


_AGENTHIFIVE_SETUP_MENU = {
    "1": "first-time",
    "2": "reconnect",
    "3": "channels",
    "first-time": "first-time",
    "setup": "first-time",
    "reconnect": "reconnect",
    "channels": "channels",
    "configure-channels": "channels",
}


def _prompt_agenthifive_setup_mode() -> str:
    """Prompt for the high-level AgentHiFive setup flow."""
    console.print("\n[bold]AgentHiFive Setup[/bold]")
    console.print("  [bold]1.[/bold] First-time setup")
    console.print("  [bold]2.[/bold] Reconnect to vault")
    console.print("  [bold]3.[/bold] Configure channels")

    while True:
        choice = typer.prompt("Choose an option", default="1").strip().lower()
        if mode := _AGENTHIFIVE_SETUP_MENU.get(choice):
            return mode
        console.print("[yellow]Choose 1, 2, or 3.[/yellow]")


def _setup_agenthifive_should_show_menu(
    *,
    base_url: str,
    bootstrap_secret: str | None,
    agent_id: str,
    private_key_path: str,
    private_key: str | None,
    token_audience: str | None,
    bearer_token: str | None,
    setup_channels: bool,
) -> bool:
    """Whether setup-agenthifive should prompt with the top-level menu."""
    return sys.stdin.isatty() and not any(
        [
            setup_channels,
            bootstrap_secret is not None,
            private_key is not None,
            token_audience is not None,
            bearer_token is not None,
            base_url != "${AGENTHIFIVE_BASE_URL}",
            agent_id != "${AGENTHIFIVE_AGENT_ID}",
            private_key_path != "${AGENTHIFIVE_PRIVATE_KEY_PATH}",
        ]
    )


def _discover_agenthifive_channel_connections(
    config_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]] | None, str | None]:
    """Best-effort discovery of healthy Telegram/Slack connections from AgentHiFive."""
    from agenthifive_nanobot.auth import build_runtime_config_from_mcp_server
    from agenthifive_nanobot.vault_client import VaultClient
    from nanobot.config.loader import load_config, resolve_config_env_vars, set_config_path

    resolved_config_path = config_path.expanduser().resolve()
    set_config_path(resolved_config_path)

    try:
        resolved_cfg = resolve_config_env_vars(load_config(resolved_config_path))
        server = resolved_cfg.tools.mcp_servers.get("agenthifive")
        if server is None:
            return None, None
        runtime = build_runtime_config_from_mcp_server(server)
    except Exception as exc:
        return None, str(exc)

    async def _fetch() -> list[dict[str, Any]]:
        client = VaultClient(
            base_url=runtime.base_url,
            auth=runtime.auth,
            timeout=runtime.timeout,
        )
        await client.start()
        return await client.list_connections()

    try:
        connections = asyncio.run(_fetch())
    except Exception as exc:
        return None, str(exc)

    result: dict[str, list[dict[str, Any]]] = {}
    for raw in connections:
        service = str(raw.get("service", "")).strip().lower()
        status = str(raw.get("status", "healthy")).strip().lower()
        if service not in {"telegram", "slack"}:
            continue
        if status and status != "healthy":
            continue
        result.setdefault(service, []).append(raw)
    return result, None


def _run_agenthifive_channel_setup(config_path: Path) -> None:
    """Configure vault-managed AgentHiFive channels without entering generic onboard."""
    from nanobot.channels.agenthifive import AgentHiFiveConfig
    from nanobot.config.loader import load_config, save_config, set_config_path

    resolved_config_path = config_path.expanduser().resolve()
    set_config_path(resolved_config_path)
    config = load_config(resolved_config_path)
    original_dump = config.model_dump(by_alias=True)

    existing_raw = getattr(config.channels, "agenthifive", None) or {}
    channel_cfg = (
        AgentHiFiveConfig.model_validate(existing_raw) if existing_raw else AgentHiFiveConfig()
    )

    def _channel_dict(name: str) -> dict[str, Any]:
        raw = getattr(config.channels, name, None) or {}
        return dict(raw)

    def _native_enabled(name: str) -> bool:
        return bool(_channel_dict(name).get("enabled"))

    def _disable_native(name: str) -> None:
        raw = _channel_dict(name)
        if raw:
            raw["enabled"] = False
            setattr(config.channels, name, raw)

    console.print("\n[bold]AgentHiFive Channels[/bold]")
    console.print(
        "[dim]Normal setup leaves NanoBot allowlists empty so AgentHiFive remains the source of truth.[/dim]"
    )

    detected, detect_error = _discover_agenthifive_channel_connections(resolved_config_path)
    if detect_error:
        console.print(
            f"[yellow]Could not inspect current AgentHiFive connections:[/yellow] {detect_error}"
        )
        console.print("[dim]Continuing with manual channel selection.[/dim]")
    elif detected is not None and detected:
        console.print("[green]✓[/green] Detected healthy AgentHiFive channel connections:")
        for service in ("telegram", "slack"):
            connections = detected.get(service, [])
            if not connections:
                continue
            display = service.capitalize()
            provider_cfg = getattr(channel_cfg.providers, service)
            state = "enabled" if provider_cfg.enabled else "disabled"
            console.print(f"  - {display} [dim]({state})[/dim]")
            for conn in connections:
                label = str(conn.get("label", "")).strip()
                if label:
                    console.print(f"    {label}")
                else:
                    console.print(f"    {display} connection")
    elif detected == {}:
        console.print(
            "[dim]No healthy Telegram or Slack connections were detected in AgentHiFive.[/dim]"
        )
        if not typer.confirm(
            "Configure channels anyway before connecting them in AgentHiFive?",
            default=False,
        ):
            console.print("[dim]Leaving AgentHiFive channel settings unchanged.[/dim]")
            return

    if channel_cfg.providers.telegram.allow_from or channel_cfg.providers.slack.allow_from:
        console.print(
            "[dim]Existing local NanoBot channel restrictions will be kept. Clear them manually later if you want AH5-only access control.[/dim]"
        )

    services_to_offer = [
        s for s in ("telegram", "slack") if detected is None or s in detected or detected == {}
    ]
    if detected and not detected.get("slack") and channel_cfg.providers.slack.enabled:
        console.print(
            "[dim]Keeping existing AgentHiFive Slack settings unchanged because no healthy Slack connection was detected.[/dim]"
        )
    if detected and not detected.get("telegram") and channel_cfg.providers.telegram.enabled:
        console.print(
            "[dim]Keeping existing AgentHiFive Telegram settings unchanged because no healthy Telegram connection was detected.[/dim]"
        )

    toggle_labels = {
        "telegram": "Telegram",
        "slack": "Slack",
    }
    toggle_map = {str(index): service for index, service in enumerate(services_to_offer, start=1)}

    def _toggle_service(service: str) -> None:
        provider_cfg = getattr(channel_cfg.providers, service)
        next_enabled = not provider_cfg.enabled
        if next_enabled and _native_enabled(service) and not provider_cfg.enabled:
            label = toggle_labels[service]
            console.print(f"\n{label} is currently configured with native NanoBot credentials.")
            console.print(
                f"[dim]Migrating keeps those credentials on disk but disables the native {label} channel.[/dim]"
            )
            if not typer.confirm(
                f"Switch {label} to AgentHiFive-managed messaging?",
                default=True,
            ):
                return
            _disable_native(service)
        provider_cfg.enabled = next_enabled

    if services_to_offer:
        while True:
            console.print("\n[bold]Channel Toggles[/bold]")
            for index, service in enumerate(services_to_offer, start=1):
                provider_cfg = getattr(channel_cfg.providers, service)
                state = "ON" if provider_cfg.enabled else "OFF"
                console.print(f"  [bold]{index}.[/bold] {toggle_labels[service]}: {state}")
            console.print("[dim]Press Enter to save, or type a number to toggle a channel.[/dim]")

            choice = typer.prompt("Toggle channel", default="").strip().lower()
            if choice == "":
                break
            service = toggle_map.get(choice)
            if service is None:
                valid = ", ".join(toggle_map)
                console.print(f"[yellow]Choose {valid}, or press Enter to save.[/yellow]")
                continue
            _toggle_service(service)

    channel_cfg.providers.telegram.reply_to_message = True
    channel_cfg.providers.slack.reply_in_thread = True

    telegram_enabled = channel_cfg.providers.telegram.enabled
    slack_enabled = channel_cfg.providers.slack.enabled

    channel_cfg.enabled = telegram_enabled or slack_enabled
    setattr(
        config.channels,
        "agenthifive",
        channel_cfg.model_dump(by_alias=True, exclude_none=True),
    )

    if config.model_dump(by_alias=True) != original_dump:
        save_config(config, resolved_config_path)
        console.print(
            f"[green]✓[/green] Saved AgentHiFive channel configuration to {resolved_config_path}"
        )
    else:
        console.print("[dim]No AgentHiFive channel changes were saved.[/dim]")

    enabled_names: list[str] = []
    if channel_cfg.providers.telegram.enabled:
        enabled_names.append("Telegram")
    if channel_cfg.providers.slack.enabled:
        enabled_names.append("Slack")
    if enabled_names:
        console.print(f"[green]✓[/green] Enabled: {', '.join(enabled_names)}")
    else:
        console.print("[dim]AgentHiFive inbound channels are disabled.[/dim]")


@app.command("setup-agenthifive")
def setup_agenthifive(
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    mcp_command: str = typer.Option(
        "agenthifive-mcp",
        "--mcp-command",
        help="Executable name to run the AgentHiFive MCP server when --mcp-path is not used",
    ),
    mcp_path: str | None = typer.Option(
        None,
        "--mcp-path",
        help="Absolute path to agenthifive-mcp/dist/index.js; uses `node <path>` when provided",
    ),
    base_url: str = typer.Option(
        "${AGENTHIFIVE_BASE_URL}",
        "--base-url",
        help="AgentHiFive base URL stored in config (env interpolation supported)",
    ),
    bootstrap_secret: str | None = typer.Option(
        None,
        "--bootstrap-secret",
        help="One-time AgentHiFive bootstrap secret (ah5b_...) for first-run setup",
    ),
    agent_id: str = typer.Option(
        "${AGENTHIFIVE_AGENT_ID}",
        "--agent-id",
        help="AgentHiFive agent ID for runtime token minting (env interpolation supported)",
    ),
    private_key_path: str = typer.Option(
        "${AGENTHIFIVE_PRIVATE_KEY_PATH}",
        "--private-key-path",
        help="Path to the AgentHiFive JWK file (env interpolation supported)",
    ),
    private_key: str | None = typer.Option(
        None,
        "--private-key",
        help="Inline AgentHiFive JWK JSON/base64 (dev/advanced use)",
    ),
    token_audience: str | None = typer.Option(
        None,
        "--token-audience",
        help="Optional token audience override for AgentHiFive agent auth",
    ),
    bearer_token: str | None = typer.Option(
        None,
        "--bearer-token",
        help="AgentHiFive bearer token fallback for manual testing (not recommended for long-running use)",
    ),
    setup_channels: bool = typer.Option(
        False,
        "--setup-channels",
        help="Open the AgentHiFive channel setup wizard",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite the existing AgentHiFive MCP config and bundled skill",
    ),
):
    """Install the AgentHiFive skill and wire its MCP server into config."""
    from nanobot.config.loader import get_config_path, load_config, save_config, set_config_path
    from nanobot.config.schema import Config, MCPServerConfig

    if config:
        config_path = Path(config).expanduser().resolve()
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")
    else:
        config_path = get_config_path()

    loaded = load_config(config_path) if config_path.exists() else Config()
    if workspace:
        loaded.agents.defaults.workspace = workspace

    mode = "channels" if setup_channels else None
    if mode is None and _setup_agenthifive_should_show_menu(
        base_url=base_url,
        bootstrap_secret=bootstrap_secret,
        agent_id=agent_id,
        private_key_path=private_key_path,
        private_key=private_key,
        token_audience=token_audience,
        bearer_token=bearer_token,
        setup_channels=setup_channels,
    ):
        mode = _prompt_agenthifive_setup_mode()
    if mode == "channels":
        if not config_path.exists():
            save_config(loaded, config_path)
            console.print(f"[green]✓[/green] Created config at {config_path}")
        console.print("\nLaunching AgentHiFive channel setup...")
        _run_agenthifive_channel_setup(config_path=config_path)
        console.print("\nNext steps:")
        console.print(f"  1. Restart gateway: [cyan]nanobot gateway --config {config_path}[/cyan]")
        console.print("  2. Connect the matching service in AgentHiFive if it is not connected yet")
        console.print("  3. Message NanoBot through the AgentHiFive channel you enabled")
        return

    base_url = _resolve_agenthifive_setup_value(
        base_url,
        prompt_text="AgentHiFive base URL",
    )
    bootstrapped_agent = False
    if bearer_token is not None:
        bearer_token = _resolve_agenthifive_setup_value(
            bearer_token,
            prompt_text="AgentHiFive bearer token",
            hide_input=True,
        )
    else:
        wants_existing_agent_auth = (
            private_key is not None
            or _agenthifive_has_configured_value(agent_id)
            or _agenthifive_has_configured_value(private_key_path)
        )
        should_bootstrap = bootstrap_secret is not None or not wants_existing_agent_auth
        if mode == "reconnect" and bootstrap_secret is None and bearer_token is None:
            should_bootstrap = typer.confirm(
                "Reconnect by bootstrapping a fresh AgentHiFive key pair?",
                default=True,
            )

        if should_bootstrap:
            bootstrap_secret = _resolve_agenthifive_setup_value(
                bootstrap_secret or "${AGENTHIFIVE_BOOTSTRAP_SECRET}",
                prompt_text="AgentHiFive bootstrap secret",
                hide_input=True,
            )
            private_key_path = _prepare_agenthifive_bootstrap_key_path(
                private_key_path,
                force=force,
            )

            try:
                private_jwk, public_jwk = _generate_agenthifive_jwk_pair()
                agent_id = _bootstrap_agenthifive_public_key(
                    base_url=base_url,
                    bootstrap_secret=bootstrap_secret,
                    public_key=public_jwk,
                )
            except RuntimeError as exc:
                console.print(f"[red]Error:[/red] {exc}")
                raise typer.Exit(1) from exc

            _write_agenthifive_private_jwk(private_key_path, private_jwk)
            private_key = None
            bootstrapped_agent = True
            console.print(
                f"[green]✓[/green] Bootstrapped AgentHiFive agent [cyan]{agent_id}[/cyan]"
            )
            console.print(
                f"[green]✓[/green] Saved private JWK to [cyan]{Path(private_key_path).expanduser()}[/cyan]"
            )
        else:
            agent_id = _resolve_agenthifive_setup_value(
                agent_id,
                prompt_text="AgentHiFive agent ID",
            )
            if private_key is None:
                private_key_path = _resolve_agenthifive_setup_value(
                    private_key_path,
                    prompt_text="Path to AgentHiFive private JWK",
                )

    workspace_path = get_workspace_path(str(loaded.workspace_path))
    download_dir = str(config_path.parent / "media" / "agenthifive")
    skill_source = _get_agenthifive_skill_source()
    skill_target = workspace_path / "skills" / "agenthifive"
    skill_target.parent.mkdir(parents=True, exist_ok=True)

    if skill_target.exists() and force:
        shutil.rmtree(skill_target)
    if not skill_target.exists():
        shutil.copytree(skill_source, skill_target)
        console.print(f"[green]✓[/green] Installed AgentHiFive skill to {skill_target}")
    else:
        console.print(f"[dim]AgentHiFive skill already present at {skill_target}[/dim]")

    defaults = _build_agenthifive_mcp_defaults(
        mcp_command=mcp_command,
        mcp_path=mcp_path,
        base_url=base_url,
        download_dir=download_dir,
        agent_id=agent_id,
        private_key_path=private_key_path,
        private_key=private_key,
        token_audience=token_audience,
        bearer_token=bearer_token,
    )
    existing = loaded.tools.mcp_servers.get("agenthifive")

    if force or existing is None:
        loaded.tools.mcp_servers["agenthifive"] = MCPServerConfig.model_validate(defaults)
    else:
        merged = _merge_missing_defaults(existing.model_dump(mode="json", by_alias=True), defaults)
        loaded.tools.mcp_servers["agenthifive"] = MCPServerConfig.model_validate(merged)

    save_config(loaded, config_path)

    console.print(f"[green]✓[/green] Saved AgentHiFive MCP config to {config_path}")
    console.print("\nNext steps:")
    if bearer_token:
        if _agenthifive_placeholder_env_name(base_url) or _agenthifive_placeholder_env_name(
            bearer_token
        ):
            console.print(
                "  1. Export [cyan]AGENTHIFIVE_BASE_URL[/cyan] and [cyan]AGENTHIFIVE_BEARER_TOKEN[/cyan]"
            )
        else:
            console.print("  1. AgentHiFive config is already stored in NanoBot's config file")
    else:
        if (
            _agenthifive_placeholder_env_name(base_url)
            or _agenthifive_placeholder_env_name(agent_id)
            or _agenthifive_placeholder_env_name(private_key_path)
        ):
            console.print(
                "  1. Export [cyan]AGENTHIFIVE_BASE_URL[/cyan], [cyan]AGENTHIFIVE_AGENT_ID[/cyan], "
                "and [cyan]AGENTHIFIVE_PRIVATE_KEY_PATH[/cyan]"
            )
        elif bootstrapped_agent:
            console.print("  1. AgentHiFive bootstrap is complete; no extra auth export is needed")
        else:
            console.print("  1. AgentHiFive config is already stored in NanoBot's config file")
    if mcp_path:
        console.print(f"  2. Start gateway: [cyan]nanobot gateway --config {config_path}[/cyan]")
    else:
        console.print(
            f"  2. Ensure [cyan]{mcp_command}[/cyan] is on PATH, then run "
            f"[cyan]nanobot gateway --config {config_path}[/cyan]"
        )
    console.print(
        "  3. In chat, ask NanoBot to list your AgentHiFive connections or perform a protected action"
    )
    console.print(
        "  4. If you want NanoBot to listen through AgentHiFive-managed channels, rerun "
        f"[cyan]nanobot setup-agenthifive --config {config_path}[/cyan] and choose "
        "[cyan]Configure channels[/cyan]"
    )


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
        consolidation_ratio=runtime_config.agents.defaults.consolidation_ratio,
        tools_config=runtime_config.tools,
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
    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)
    cfg = _load_runtime_config(config, workspace)
    _run_gateway(cfg, port=port)


def _run_gateway(
    config: Config,
    *,
    port: int | None = None,
    open_browser_url: str | None = None,
) -> None:
    """Shared gateway runtime; ``open_browser_url`` opens a tab once channels are up."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.cron import CronTool
    from nanobot.agent.tools.message import MessageTool
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.session.manager import SessionManager

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
    # AgentHiFive adapter (optional — starts approval poller if configured)
    ah5_adapter = None
    ah5_hooks = []
    ah5_server = config.tools.mcp_servers.get("agenthifive")
    if ah5_server:
        try:
            from agenthifive_nanobot.adapter import AgentHiFiveAdapter

            ah5_adapter = AgentHiFiveAdapter.from_mcp_server_config(
                bus=bus, server_config=ah5_server
            )
            ah5_hooks = [ah5_adapter.hook]
            console.print("[green]✓[/green] AgentHiFive adapter enabled (approval poller + hook)")
        except ValueError as exc:
            console.print(f"[yellow]Warning:[/yellow] AgentHiFive adapter disabled: {exc}")
        except ImportError:
            pass  # agenthifive_nanobot not installed — skip silently

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
        consolidation_ratio=config.agents.defaults.consolidation_ratio,
        tools_config=config.tools,
        hooks=ah5_hooks,
    )

    from nanobot.agent.loop import UNIFIED_SESSION_KEY
    from nanobot.bus.events import OutboundMessage

    def _channel_session_key(channel: str, chat_id: str) -> str:
        return (
            UNIFIED_SESSION_KEY
            if config.agents.defaults.unified_session
            else f"{channel}:{chat_id}"
        )

    async def _deliver_to_channel(msg: OutboundMessage, *, record: bool = False) -> None:
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
            session = session_manager.get_or_create(_channel_session_key(msg.channel, msg.chat_id))
            session.add_message("assistant", msg.content, _channel_delivery=True)
            session_manager.save(session)
        await bus.publish_outbound(msg)

    message_tool = getattr(agent, "tools", {}).get("message")
    if isinstance(message_tool, MessageTool):
        message_tool.set_send_callback(_deliver_to_channel)

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

        async def _silent(*_args, **_kwargs):
            pass

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
                response,
                reminder_note,
                provider,
                agent.model,
            )
            if should_notify:
                await _deliver_to_channel(
                    OutboundMessage(
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to,
                        content=response,
                    ),
                    record=True,
                )
        return response

    cron.on_job = on_cron_job

    # Create channel manager (forwards SessionManager so the WebSocket channel
    # can serve the embedded webui's REST surface).
    channels = ChannelManager(config, bus, session_manager=session_manager)

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
        """Phase 2: execute heartbeat tasks through the full agent loop."""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
            pass

        resp = await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

        # Keep a small tail of heartbeat history so the loop stays bounded
        # without losing all short-term context between runs.
        session = agent.sessions.get_or_create("heartbeat")
        session.retain_recent_legal_suffix(hb_cfg.keep_recent_messages)
        agent.sessions.save(session)

        return resp.content if resp else ""

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel.

        In addition to publishing the outbound message, this injects the
        delivered text as an assistant turn into the *target channel's*
        session.  Without this, a user reply on the channel (e.g. "Sure")
        lands in a session that has no context about the heartbeat message
        and the agent cannot follow through.
        """
        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # No external channel available to deliver to

        await _deliver_to_channel(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response),
            record=True,
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
    # Register Dream system job (always-on, idempotent on restart)
    dream_cfg = config.agents.defaults.dream
    if dream_cfg.model_override:
        agent.dream.model = dream_cfg.model_override
    agent.dream.max_batch_size = dream_cfg.max_batch_size
    agent.dream.max_iterations = dream_cfg.max_iterations
    agent.dream.annotate_line_ages = dream_cfg.annotate_line_ages
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
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
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
            await heartbeat.start()
            if ah5_adapter:
                await ah5_adapter.start()
            tasks = [
                agent.run(),
                channels.start_all(),
                _health_server(config.gateway.host, port),
            ]
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
            if ah5_adapter:
                await ah5_adapter.stop()
            await agent.close_mcp()
            heartbeat.stop()
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
        consolidation_ratio=config.agents.defaults.consolidation_ratio,
        tools_config=config.tools,
    )
    restart_notice = consume_restart_notice_from_env()
    if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
        _print_agent_response(
            format_restart_completed_message(restart_notice.started_at_raw),
            render_markdown=False,
        )

    # Shared reference for progress callbacks
    _thinking: ThinkingSpinner | None = None

    async def _cli_progress(content: str, *, tool_hint: bool = False, **_kwargs: Any) -> None:
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
            f"{__logo__} Interactive mode [bold blue]({config.agents.defaults.model})[/bold blue] "
            f"(type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n"
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


@app.command("setup-channels")
def setup_channels(
    channel_name: str | None = typer.Argument(
        None,
        help="Optional channel name to configure directly (e.g. telegram)",
    ),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Configure NanoBot chat channels like Telegram, Discord, or Slack."""
    from nanobot.config.loader import get_config_path

    resolved_config_path = (
        Path(config_path).expanduser().resolve() if config_path else get_config_path()
    )
    _run_setup_channels(config_path=resolved_config_path, channel_name=channel_name)


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
