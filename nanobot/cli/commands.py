"""CLI commands for nanobot."""

import asyncio
import os
import select
import signal
import sys
from pathlib import Path

import httpx
import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from nanobot import __logo__, __version__

app = typer.Typer(
    name="nanobot",
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

    history_file = Path.home() / ".nanobot" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


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
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, save_config
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()

    # Create default config
    config = Config()
    _interactive_onboard_setup(config)
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")

    # Create default bootstrap files
    _create_workspace_templates(workspace)

    console.print(f"\n{__logo__} nanobot is ready!")
    provider_name = config.get_provider_name(config.agents.defaults.model)
    if provider_name:
        console.print(f"  Provider: [cyan]{provider_name}[/cyan]")
    console.print(f"  Model: [cyan]{config.agents.defaults.model}[/cyan]")
    if config.tools.web.search.api_key:
        console.print("  Web search: [green]Brave enabled[/green]")
    else:
        console.print(
            "  Web search: [yellow]Brave disabled[/yellow] (model-native search may still work)"
        )

    console.print("\nNext steps:")
    console.print('  1. Chat: [cyan]nanobot agent -m "Hello!"[/cyan]')
    console.print("  2. Start gateway: [cyan]nanobot gateway[/cyan]")
    console.print(
        "\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]"
    )


def _interactive_onboard_setup(config) -> None:
    """Interactive setup for provider/model/search defaults."""
    console.print("\n[bold]Interactive setup[/bold] (press Enter to accept defaults)")

    provider_options = [
        ("OpenRouter (recommended gateway)", "openrouter", "anthropic/claude-opus-4-5"),
        ("Anthropic", "anthropic", "claude-opus-4-5"),
        ("OpenAI", "openai", "gpt-4.1"),
        ("DeepSeek", "deepseek", "deepseek-chat"),
        ("Gemini", "gemini", "gemini-2.5-pro"),
        ("Moonshot", "moonshot", "kimi-k2.5"),
        ("DashScope (Qwen)", "dashscope", "qwen-max"),
        ("Zhipu", "zhipu", "glm-4"),
        ("MiniMax", "minimax", "MiniMax-M2.1"),
        ("AiHubMix", "aihubmix", "claude-opus-4.1"),
        ("vLLM / local OpenAI-compatible", "vllm", "meta-llama/Llama-3.1-8B-Instruct"),
        ("Ollama Local", "ollama_local", "llama3.2"),
        ("Ollama Cloud", "ollama_cloud", "gpt-oss:20b-cloud"),
    ]

    console.print("\n[bold]1) Choose your primary LLM provider[/bold]")
    for idx, (label, _, _) in enumerate(provider_options, start=1):
        console.print(f"  {idx}. {label}")

    selected = typer.prompt(
        "Provider number",
        type=int,
        default=1,
        show_default=True,
    )
    if selected < 1 or selected > len(provider_options):
        selected = 1

    provider_label, provider_key, default_model = provider_options[selected - 1]
    console.print(f"Selected: [cyan]{provider_label}[/cyan]")

    provider_cfg = getattr(config.providers, provider_key)
    if provider_key == "ollama_local":
        provider_cfg.api_base = typer.prompt(
            "Ollama local base URL",
            default="http://localhost:11434",
            show_default=True,
        ).strip()
        provider_cfg.api_key = ""
        model = typer.prompt(
            "Model name",
            default=default_model,
            show_default=True,
        ).strip()
        config.agents.defaults.model = model or default_model
    elif provider_key == "vllm":
        provider_cfg.api_base = typer.prompt(
            "Local OpenAI-compatible base URL",
            default="http://localhost:8000/v1",
            show_default=True,
        ).strip()
        provider_cfg.api_key = typer.prompt(
            "API key (optional for local)",
            default="",
            show_default=False,
        ).strip()
        model = typer.prompt(
            "Model name",
            default=default_model,
            show_default=True,
        ).strip()
        config.agents.defaults.model = model or default_model
    elif provider_key == "ollama_cloud":
        provider_cfg.api_base = typer.prompt(
            "Ollama cloud base URL",
            default="https://ollama.com",
            show_default=True,
        ).strip()
        while True:
            key = typer.prompt("Ollama cloud API key", default="", show_default=False).strip()
            if key:
                provider_cfg.api_key = key
                break
            console.print("[yellow]API key is required for Ollama Cloud.[/yellow]")

        console.print("\n[bold]Model selection for Ollama Cloud[/bold]")
        console.print("  1. Manual model input")
        console.print("  2. Fetch model list from Ollama Cloud (recommended)")
        cloud_model_mode = typer.prompt("Mode", type=int, default=2, show_default=True)

        if cloud_model_mode == 2:
            models, error = _fetch_ollama_cloud_models(
                api_base=provider_cfg.api_base,
                api_key=provider_cfg.api_key,
            )
            if models:
                keyword = (
                    typer.prompt(
                        "Filter keyword (optional)",
                        default="",
                        show_default=False,
                    )
                    .strip()
                    .lower()
                )
                if keyword:
                    filtered_models = [
                        model_name for model_name in models if keyword in model_name.lower()
                    ]
                    if filtered_models:
                        models = filtered_models
                    else:
                        console.print(
                            "[yellow]No models matched filter, showing full list.[/yellow]"
                        )

                max_display = min(len(models), 30)
                console.print(f"Found {len(models)} model(s). Showing first {max_display}:")
                for index, model_name in enumerate(models[:max_display], start=1):
                    console.print(f"  {index}. {model_name}")

                selected_model = typer.prompt(
                    "Model number",
                    type=int,
                    default=1,
                    show_default=True,
                )
                if selected_model < 1:
                    selected_model = 1
                if selected_model > max_display:
                    selected_model = max_display
                config.agents.defaults.model = models[selected_model - 1]
                console.print(f"Selected model: [cyan]{config.agents.defaults.model}[/cyan]")
            else:
                console.print(
                    "[yellow]Failed to fetch model list; falling back to manual input.[/yellow]"
                )
                if error:
                    console.print(f"[dim]{error}[/dim]")
                model = typer.prompt(
                    "Model name",
                    default=default_model,
                    show_default=True,
                ).strip()
                config.agents.defaults.model = model or default_model
        else:
            model = typer.prompt(
                "Model name",
                default=default_model,
                show_default=True,
            ).strip()
            config.agents.defaults.model = model or default_model
    else:
        while True:
            key = typer.prompt(f"{provider_label} API key", default="", show_default=False).strip()
            if key:
                provider_cfg.api_key = key
                break
            console.print("[yellow]API key is required.[/yellow]")
        if typer.confirm("Set custom API base URL?", default=False):
            provider_cfg.api_base = (
                typer.prompt("Custom API base URL", default="", show_default=False).strip() or None
            )
        model = typer.prompt(
            "Model name",
            default=default_model,
            show_default=True,
        ).strip()
        config.agents.defaults.model = model or default_model

    console.print("\n[bold]2) Configure web search & fetch tools[/bold]")
    console.print("  Search provider options:")
    console.print("    1. Brave")
    console.print("    2. Ollama web_search")
    console.print("    3. Hybrid (Brave first, fallback to Ollama)")
    search_mode = typer.prompt("Search mode", type=int, default=1, show_default=True)

    if search_mode == 2:
        config.tools.web.search.provider = "ollama"
    elif search_mode == 3:
        config.tools.web.search.provider = "hybrid"
    else:
        config.tools.web.search.provider = "brave"

    if config.tools.web.search.provider in {"brave", "hybrid"}:
        brave_key = typer.prompt("Brave Search API key", default="", show_default=False).strip()
        config.tools.web.search.api_key = brave_key
        if not brave_key:
            console.print("[yellow]Brave key not set: Brave search may be unavailable.[/yellow]")
    else:
        config.tools.web.search.api_key = ""

    if config.tools.web.search.provider in {"ollama", "hybrid"}:
        default_ollama_base = (
            config.providers.ollama_cloud.api_base
            if config.providers.ollama_cloud.api_base
            else "https://ollama.com"
        )
        default_ollama_key = config.providers.ollama_cloud.api_key or ""

        config.tools.web.search.ollama_api_base = typer.prompt(
            "Ollama web_search base URL",
            default=default_ollama_base,
            show_default=True,
        ).strip()

        if default_ollama_key:
            use_provider_key = typer.confirm(
                "Reuse providers.ollamaCloud.apiKey for Ollama web_search?",
                default=True,
            )
            if use_provider_key:
                config.tools.web.search.ollama_api_key = default_ollama_key
            else:
                config.tools.web.search.ollama_api_key = typer.prompt(
                    "Ollama web_search API key",
                    default="",
                    show_default=False,
                ).strip()
        else:
            config.tools.web.search.ollama_api_key = typer.prompt(
                "Ollama web_search API key",
                default="",
                show_default=False,
            ).strip()

        if not config.tools.web.search.ollama_api_key:
            console.print(
                "[yellow]Ollama API key not set: Ollama web_search may be unavailable.[/yellow]"
            )
    else:
        config.tools.web.search.ollama_api_key = ""

    console.print("\n  Fetch provider options:")
    console.print("    1. nanobot web_fetch (default)")
    console.print("    2. Ollama web_fetch")
    console.print("    3. Hybrid (nanobot first, fallback to Ollama)")
    fetch_mode = typer.prompt("Fetch mode", type=int, default=1, show_default=True)

    if fetch_mode == 2:
        config.tools.web.fetch.provider = "ollama"
    elif fetch_mode == 3:
        config.tools.web.fetch.provider = "hybrid"
    else:
        config.tools.web.fetch.provider = "nanobot"

    if config.tools.web.fetch.provider in {"ollama", "hybrid"}:
        default_fetch_base = config.tools.web.search.ollama_api_base or "https://ollama.com"
        default_fetch_key = config.tools.web.search.ollama_api_key or ""
        config.tools.web.fetch.ollama_api_base = typer.prompt(
            "Ollama web_fetch base URL",
            default=default_fetch_base,
            show_default=True,
        ).strip()

        if default_fetch_key:
            use_search_key = typer.confirm(
                "Reuse Ollama web_search API key for web_fetch?",
                default=True,
            )
            if use_search_key:
                config.tools.web.fetch.ollama_api_key = default_fetch_key
            else:
                config.tools.web.fetch.ollama_api_key = typer.prompt(
                    "Ollama web_fetch API key",
                    default="",
                    show_default=False,
                ).strip()
        else:
            config.tools.web.fetch.ollama_api_key = typer.prompt(
                "Ollama web_fetch API key",
                default="",
                show_default=False,
            ).strip()

        if not config.tools.web.fetch.ollama_api_key:
            console.print(
                "[yellow]Ollama API key not set: Ollama web_fetch may be unavailable.[/yellow]"
            )
    else:
        config.tools.web.fetch.ollama_api_key = ""


def _fetch_ollama_cloud_models(api_base: str, api_key: str) -> tuple[list[str], str | None]:
    """Fetch available model names from Ollama cloud endpoints.

    Tries Ollama native endpoint first (/api/tags), then OpenAI-compatible
    endpoint (/v1/models) as fallback.
    """
    base = (api_base or "").rstrip("/")
    if not base:
        return [], "Missing apiBase"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    endpoint_candidates: list[str] = []
    if base.endswith("/api"):
        endpoint_candidates.append(f"{base}/tags")
    else:
        endpoint_candidates.append(f"{base}/api/tags")

    if base.endswith("/v1"):
        endpoint_candidates.append(f"{base}/models")
    else:
        endpoint_candidates.append(f"{base}/v1/models")

    errors: list[str] = []
    for endpoint in endpoint_candidates:
        try:
            response = httpx.get(endpoint, headers=headers, timeout=10.0)
            response.raise_for_status()
            payload = response.json()

            models: list[str] = []
            if isinstance(payload.get("models"), list):
                for item in payload["models"]:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("model")
                        if isinstance(name, str) and name:
                            models.append(name)
            if isinstance(payload.get("data"), list):
                for item in payload["data"]:
                    if isinstance(item, dict):
                        name = item.get("id")
                        if isinstance(name, str) and name:
                            models.append(name)

            uniq_models = sorted(set(models))
            if uniq_models:
                return uniq_models, None
            errors.append(f"{endpoint}: empty model list")
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")

    return [], "; ".join(errors)


def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
""",
        "SOUL.md": """# Soul

I am nanobot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }

    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")

    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)

---

This file is for human-readable notes. Runtime long-term snapshot memory lives in memory/LTM_SNAPSHOT.json.
Self-improvement lessons live in memory/LESSONS.jsonl.
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")

    # Create skills directory for custom user skills
    skills_dir = workspace / "skills"
    skills_dir.mkdir(exist_ok=True)


def _make_provider(config):
    """Create LiteLLMProvider from config. Validates required provider fields."""
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.providers.registry import find_by_name

    p = config.get_provider()
    provider_name = config.get_provider_name()
    spec = find_by_name(provider_name) if provider_name else None
    model = config.agents.defaults.model

    has_valid_provider = False
    if p:
        if spec and spec.is_local:
            has_valid_provider = bool(p.api_base)
        elif provider_name == "ollama_cloud":
            has_valid_provider = bool(p.api_key and p.api_base)
        else:
            has_valid_provider = bool(p.api_key)

    if not has_valid_provider and not model.startswith("bedrock/"):
        if spec and spec.is_local:
            console.print("[red]Error: Local provider requires apiBase.[/red]")
            console.print("Set providers.<name>.apiBase in ~/.nanobot/config.json")
        elif provider_name == "ollama_cloud":
            console.print("[red]Error: Ollama Cloud requires both apiKey and apiBase.[/red]")
            console.print("Set providers.ollamaCloud.apiKey and providers.ollamaCloud.apiBase")
        else:
            console.print("[red]Error: No API key configured.[/red]")
            console.print("Set one in ~/.nanobot/config.json under providers section")
        raise typer.Exit(1)

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.session.manager import SessionManager

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")

    config = load_config()
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(
        config.workspace_path,
        compact_threshold_messages=config.agents.sessions.compact_threshold_messages,
        compact_threshold_bytes=config.agents.sessions.compact_threshold_bytes,
        compact_keep_messages=config.agents.sessions.compact_keep_messages,
    )

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        web_config=config.tools.web,
        exec_config=config.tools.exec,
        memory_config=config.agents.memory,
        self_improvement_config=config.agents.self_improvement,
        session_config=config.agents.sessions,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response or "",
                )
            )
        return response

    cron.on_job = on_cron_job

    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")

    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True,
    )

    # Create channel manager
    channels = ChannelManager(config, bus, session_manager=session_manager)

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print("[green]✓[/green] Heartbeat: every 30m")

    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
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
    from nanobot.config.loader import load_config

    config = load_config()

    bus = MessageBus()
    provider = _make_provider(config)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        web_config=config.tools.web,
        exec_config=config.tools.exec,
        memory_config=config.agents.memory,
        self_improvement_config=config.agents.self_improvement,
        session_config=config.agents.sessions,
        restrict_to_workspace=config.tools.restrict_to_workspace,
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext

            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]nanobot is thinking...[/dim]", spinner="dots")

    if message:
        # Single message mode
        async def run_once():
            try:
                with _thinking_ctx():
                    response = await agent_loop.process_direct(message, session_id)
                _print_agent_response(response, render_markdown=markdown)
            finally:
                agent_loop.stop()

        asyncio.run(run_once())
    else:
        # Interactive mode
        _init_prompt_session()
        console.print(
            f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n"
        )

        def _exit_on_sigint(signum, frame):
            agent_loop.stop()
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

        async def run_interactive():
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

                        with _thinking_ctx():
                            response = await agent_loop.process_direct(user_input, session_id)
                        _print_agent_response(response, render_markdown=markdown)
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

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row("WhatsApp", "✓" if wa.enabled else "✗", wa.bridge_url)

    dc = config.channels.discord
    table.add_row("Discord", "✓" if dc.enabled else "✗", dc.gateway_url)

    # Feishu
    fs = config.channels.feishu
    fs_config = f"app_id: {fs.app_id[:10]}..." if fs.app_id else "[dim]not configured[/dim]"
    table.add_row("Feishu", "✓" if fs.enabled else "✗", fs_config)

    # Mochat
    mc = config.channels.mochat
    mc_base = mc.base_url or "[dim]not configured[/dim]"
    table.add_row("Mochat", "✓" if mc.enabled else "✗", mc_base)

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row("Telegram", "✓" if tg.enabled else "✗", tg_config)

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row("Slack", "✓" if slack.enabled else "✗", slack_config)

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    user_bridge = Path.home() / ".nanobot" / "bridge"

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    if not shutil.which("npm"):
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
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess

    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Memory Commands
# ============================================================================


memory_app = typer.Typer(help="Manage agent memory")
app.add_typer(memory_app, name="memory")


def _new_memory_store(config):
    """Create a memory store using config defaults."""
    from nanobot.agent.memory import MemoryStore

    return MemoryStore(
        workspace=config.workspace_path,
        flush_every_updates=config.agents.memory.flush_every_updates,
        flush_interval_seconds=config.agents.memory.flush_interval_seconds,
        short_term_turns=config.agents.memory.short_term_turns,
        pending_limit=config.agents.memory.pending_limit,
        self_improvement_enabled=config.agents.self_improvement.enabled,
        max_lessons_in_prompt=config.agents.self_improvement.max_lessons_in_prompt,
        min_lesson_confidence=config.agents.self_improvement.min_lesson_confidence,
        max_lessons=config.agents.self_improvement.max_lessons,
    )


@memory_app.command("status")
def memory_status():
    """Show memory runtime status."""
    from nanobot.config.loader import load_config

    config = load_config()
    memory = _new_memory_store(config)
    status = memory.get_status()

    table = Table(title="Memory Status")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    fields = [
        ("Snapshot Path", status["snapshot_path"]),
        ("Audit Path", status["audit_path"]),
        ("Snapshot Exists", "yes" if status["snapshot_exists"] else "no"),
        ("Long-term Items", str(status["ltm_items"])),
        ("Short-term Sessions", str(status["short_term_sessions"])),
        ("Pending Sessions", str(status["pending_sessions"])),
        ("Dirty Updates", str(status["dirty_updates"])),
        ("Flush Every Updates", str(status["flush_every_updates"])),
        ("Flush Interval Seconds", str(status["flush_interval_seconds"])),
        ("Last Snapshot At", status["last_snapshot_at"] or "-"),
        ("Self Improvement Enabled", "yes" if status["self_improvement_enabled"] else "no"),
        ("Lessons Count", str(status["lessons_count"])),
        ("Lessons File", status["lessons_file"]),
        ("Lessons Audit File", status["lessons_audit_file"]),
        ("Max Lessons In Prompt", str(status["max_lessons_in_prompt"])),
        ("Min Lesson Confidence", str(status["min_lesson_confidence"])),
        ("Max Lessons", str(status["max_lessons"])),
    ]

    for name, value in fields:
        table.add_row(name, value)

    console.print(table)


@memory_app.command("flush")
def memory_flush():
    """Flush in-memory memory state to disk."""
    from nanobot.config.loader import load_config

    config = load_config()
    memory = _new_memory_store(config)
    changed = memory.flush(force=True)
    if changed:
        console.print("[green]✓[/green] Memory flushed")
    else:
        console.print("[dim]No pending memory updates[/dim]")


@memory_app.command("compact")
def memory_compact(
    max_items: int = typer.Option(300, "--max-items", help="Maximum long-term items to keep"),
):
    """Compact long-term snapshot memory."""
    from nanobot.config.loader import load_config

    config = load_config()
    memory = _new_memory_store(config)
    removed = memory.compact(max_items=max_items, auto_flush=False)
    memory.flush(force=True)
    console.print(f"[green]✓[/green] Memory compacted (removed {removed} items)")


memory_lessons_app = typer.Typer(help="Manage self-improvement lessons")
memory_app.add_typer(memory_lessons_app, name="lessons")


@memory_lessons_app.command("status")
def memory_lessons_status():
    """Show self-improvement lesson status."""
    from nanobot.config.loader import load_config

    config = load_config()
    memory = _new_memory_store(config)
    status = memory.get_status()

    table = Table(title="Lessons Status")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Enabled", "yes" if status["self_improvement_enabled"] else "no")
    table.add_row("Lessons Count", str(status["lessons_count"]))
    table.add_row("Lessons File", status["lessons_file"])
    table.add_row("Lessons Audit File", status["lessons_audit_file"])
    table.add_row("Max Lessons In Prompt", str(status["max_lessons_in_prompt"]))
    table.add_row("Min Lesson Confidence", str(status["min_lesson_confidence"]))
    table.add_row("Max Lessons", str(status["max_lessons"]))
    console.print(table)


@memory_lessons_app.command("compact")
def memory_lessons_compact(
    max_lessons: int = typer.Option(200, "--max-lessons", help="Maximum lessons to keep"),
):
    """Compact self-improvement lessons."""
    from nanobot.config.loader import load_config

    config = load_config()
    memory = _new_memory_store(config)
    removed = memory.compact_lessons(max_lessons=max_lessons, auto_flush=False)
    memory.flush(force=True)
    console.print(f"[green]✓[/green] Lessons compacted (removed {removed} items)")


@memory_lessons_app.command("reset")
def memory_lessons_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Reset without confirmation"),
):
    """Reset all self-improvement lessons."""
    from nanobot.config.loader import load_config

    if not yes and not typer.confirm("Reset all lessons?"):
        console.print("[dim]Canceled[/dim]")
        return

    config = load_config()
    memory = _new_memory_store(config)
    removed = memory.reset_lessons()
    console.print(f"[green]✓[/green] Lessons reset (removed {removed} items)")


# ============================================================================
# Session Commands
# ============================================================================


session_app = typer.Typer(help="Manage conversation sessions")
app.add_typer(session_app, name="session")


def _new_session_manager(config):
    """Create a session manager using config defaults."""
    from nanobot.session.manager import SessionManager

    return SessionManager(
        config.workspace_path,
        compact_threshold_messages=config.agents.sessions.compact_threshold_messages,
        compact_threshold_bytes=config.agents.sessions.compact_threshold_bytes,
        compact_keep_messages=config.agents.sessions.compact_keep_messages,
    )


@session_app.command("compact")
def session_compact(
    session_id: str | None = typer.Option(None, "--session", "-s", help="Session ID to compact"),
    all: bool = typer.Option(False, "--all", "-a", help="Compact all sessions"),
):
    """Compact session storage files."""
    from nanobot.config.loader import load_config

    config = load_config()
    manager = _new_session_manager(config)

    if all:
        compacted = manager.compact_all()
        console.print(f"[green]✓[/green] Compacted {compacted} sessions")
        return

    if not session_id:
        console.print("[red]Error: use --session <id> or --all[/red]")
        raise typer.Exit(1)

    if manager.compact(session_id):
        console.print(f"[green]✓[/green] Compacted session {session_id}")
    else:
        console.print(f"[red]Session {session_id} not found[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    jobs = service.list_jobs(include_disabled=all)

    if not jobs:
        console.print("No scheduled jobs.")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")

    import time

    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"

        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000)
            )
            next_run = next_time

        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"

        table.add_row(job.id, job.name, sched, status, next_run)

    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(
        None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"
    ),
):
    """Add a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronSchedule

    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime

        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )

    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    async def run():
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print("[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


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
        active_provider = config.get_provider_name(config.agents.defaults.model)

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            active_badge = " [cyan](active)[/cyan]" if spec.name == active_provider else ""
            if spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}{active_badge}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}{active_badge}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                if has_key and p.api_base:
                    console.print(f"{spec.label}{active_badge}: [green]✓[/green] ({p.api_base})")
                else:
                    console.print(
                        f"{spec.label}{active_badge}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                    )


if __name__ == "__main__":
    app()
