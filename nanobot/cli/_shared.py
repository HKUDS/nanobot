"""Shared CLI factories, utilities, and singletons.

Extracted from ``commands.py`` so that every CLI sub-module can import
lightweight helpers without pulling in the full command tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from nanobot import __logo__, __version__
from nanobot.config.schema import AgentConfig

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import Config
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

console = Console()

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def version_callback(value: bool) -> None:
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


def _sys_stderr(message: str) -> None:
    """Write to stderr -- needed as a callable sink for loguru."""
    import sys

    sys.stderr.write(message)


def _configure_log_sink(config: Config, log: Any) -> None:
    """Apply structured logging settings from ``config.log``.

    Adds a JSON file sink when ``config.log.json_file`` is set, and enables
    loguru's ``serialize`` mode when ``config.log.json`` is ``True``.
    """
    log_cfg = config.log
    if log_cfg.json_file:
        path = Path(log_cfg.json_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        log.add(
            str(path),
            level=log_cfg.level,
            serialize=True,
            rotation="10 MB",
            retention="7 days",
            enqueue=True,
        )
    if log_cfg.json_stdout:
        # Replace default stderr sink with serialized (JSON) output
        log.remove()
        log.add(
            _sys_stderr,
            level=log_cfg.level,
            serialize=True,
        )


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def _make_provider(config: Config) -> Any:
    """Create the appropriate LLM provider from config."""
    from nanobot.providers.custom_provider import CustomProvider
    from nanobot.providers.litellm_provider import LiteLLMProvider

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # OpenAI Codex (OAuth)
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        return OpenAICodexProvider(default_model=model)

    # Custom: direct OpenAI-compatible endpoint, bypasses LiteLLM
    if provider_name == "custom":
        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )

    from nanobot.providers.registry import find_by_name

    spec = find_by_name(provider_name or "")
    if not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and spec.is_oauth):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers section")
        raise typer.Exit(1)

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
        llm_timeout_s=config.llm.timeout_s,
        llm_max_retries=config.llm.max_retries,
        max_budget_usd=config.agents.defaults.max_session_cost_usd,
    )


def _make_agent_config(config: Config) -> AgentConfig:
    """Build an ``AgentConfig`` from the root ``Config``.

    Feature flags from ``config.features`` act as master kill-switches:
    when a flag is ``False``, the corresponding ``AgentConfig`` field is
    forced off regardless of the per-agent default.
    """
    overrides: dict[str, object] = {
        "restrict_to_workspace": config.tools.restrict_to_workspace,
    }

    # Apply feature-flag overrides (only disable, never force-enable)
    feat = config.features
    if not feat.planning_enabled:
        overrides["planning_enabled"] = False
    if not feat.verification_enabled:
        overrides["verification_mode"] = "off"
    if not feat.delegation_enabled:
        overrides["delegation_enabled"] = False
    if not feat.memory_enabled:
        overrides["memory_enabled"] = False
    if not feat.skills_enabled:
        overrides["skills_enabled"] = False
    if not feat.streaming_enabled:
        overrides["streaming_enabled"] = False

    return AgentConfig.from_defaults(config.agents.defaults, **overrides)


def _make_agent_loop(
    config: Config,
    *,
    bus: MessageBus | None = None,
    cron_service: CronService | None = None,
    session_manager: SessionManager | None = None,
) -> AgentLoop:
    """Construct an ``AgentLoop`` with the standard CLI wiring.

    Consolidates the duplicated setup pattern used by gateway, ui, agent,
    cron run, and routing replay.  Caller-specific overrides (``bus``,
    ``cron_service``, ``session_manager``) are forwarded when provided.

    Heavy imports are deferred to keep CLI startup fast.
    """
    from nanobot.agent.agent_factory import build_agent
    from nanobot.bus.queue import MessageBus as _MessageBus

    if bus is None:
        bus = _MessageBus()

    provider = _make_provider(config)

    return build_agent(
        bus=bus,
        provider=provider,
        config=_make_agent_config(config),
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron_service,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        routing_config=config.agents.routing,
    )


# ---------------------------------------------------------------------------
# Top-level commands (logic only -- decorators stay in commands.py)
# ---------------------------------------------------------------------------


def _create_workspace_templates(workspace: Path) -> None:
    """Create default workspace template files from bundled templates."""
    from importlib.resources import files as pkg_files

    templates_dir = pkg_files("nanobot") / "templates"

    for item in templates_dir.iterdir():
        if not item.name.endswith(".md"):
            continue
        dest = workspace / item.name
        if not dest.exists():
            dest.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
            console.print(f"  [dim]Created {item.name}[/dim]")

    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)

    memory_template = templates_dir / "memory" / "MEMORY.md"
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(memory_template.read_text(encoding="utf-8"), encoding="utf-8")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")

    history_file = memory_dir / "HISTORY.md"
    if not history_file.exists():
        history_file.write_text("", encoding="utf-8")
        console.print("  [dim]Created memory/HISTORY.md[/dim]")

    events_file = memory_dir / "events.jsonl"
    if not events_file.exists():
        events_file.write_text("", encoding="utf-8")
        console.print("  [dim]Created memory/events.jsonl[/dim]")

    profile_file = memory_dir / "profile.json"
    if not profile_file.exists():
        profile_file.write_text("{}", encoding="utf-8")
        console.print("  [dim]Created memory/profile.json[/dim]")

    (workspace / "skills").mkdir(exist_ok=True)


def onboard() -> None:
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, load_config, save_config
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print(
            "  [bold]N[/bold] = refresh config, keeping existing values and adding new fields"
        )
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()
            save_config(config)
            console.print(
                f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)"
            )
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()

    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace}")

    # Create default bootstrap files
    _create_workspace_templates(workspace)

    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print('  2. Chat: [cyan]nanobot agent -m "Hello!"[/cyan]')
    console.print(
        "\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]"
    )


def status() -> None:
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
