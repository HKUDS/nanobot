"""CLI commands for nanobot."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from nanobot import __version__, __logo__

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()


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
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")
    
    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")
    
    # Create default bootstrap files
    _create_workspace_templates(workspace)
    
    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")




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
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    import html
    import os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import parse_qs, urlparse

    from nanobot.config.loader import load_config, save_config, get_config_path, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")

    config = load_config()

    def _escape(value: str) -> str:
        return html.escape(value or "")

    def _is_true(value: str | None) -> bool:
        return (value or "").lower() in {"1", "true", "yes", "on"}

    def _get_field(fields: dict[str, list[str]], name: str) -> str:
        return (fields.get(name, [""])[0] or "").strip()

    def _render_settings_page(saved: bool = False, error: str | None = None) -> str:
        cfg = load_config()
        cfg_path = get_config_path()
        write_mode = os.getenv("NANOBOT_WRITE_CONFIG", "auto")

        together_set = bool(cfg.providers.together.api_key)
        openrouter_set = bool(cfg.providers.openrouter.api_key)
        brave_set = bool(cfg.tools.web.search.api_key)
        telegram_set = bool(cfg.channels.telegram.token)

        allow_from = ", ".join(cfg.channels.telegram.allow_from)
        notice = ""
        if saved:
            notice = "<div class='notice ok'>Saved. Restart the service to apply changes.</div>"
        elif error:
            notice = f"<div class='notice err'>Error: {_escape(error)}</div>"

        write_note = ""
        if _is_true(write_mode):
            write_note = (
                "<div class='notice warn'>NANOBOT_WRITE_CONFIG is enabled. "
                "Config will be overwritten on restart. Set it to 0 after the first save.</div>"
            )
        priority_note = (
            "<div class='notice warn'>Provider priority: OpenRouter > Together > Anthropic > OpenAI "
            "> Gemini > Zhipu > vLLM.</div>"
        )

        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>nanobot Settings</title>
    <style>
      :root {{ color-scheme: light; }}
      body {{ margin: 0; font-family: Arial, sans-serif; background: #f6f7fb; color: #111; }}
      header {{ background: #0f172a; color: #fff; padding: 24px; }}
      header h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
      header p {{ margin: 0; opacity: 0.9; }}
      main {{ max-width: 900px; margin: 0 auto; padding: 24px; }}
      .card {{ background: #fff; border: 1px solid #e6e8ef; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
      .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
      label {{ display: block; font-weight: 600; margin-bottom: 6px; }}
      input[type="text"], input[type="password"] {{
        width: 100%; padding: 10px 12px; border: 1px solid #d4d7e0; border-radius: 8px;
      }}
      .hint {{ font-size: 12px; color: #555; margin-top: 6px; }}
      .notice {{ padding: 10px 12px; border-radius: 8px; margin-bottom: 12px; }}
      .notice.ok {{ background: #ecfdf3; border: 1px solid #b7f3cf; color: #065f46; }}
      .notice.err {{ background: #fff1f2; border: 1px solid #fecdd3; color: #9f1239; }}
      .notice.warn {{ background: #fff7ed; border: 1px solid #fed7aa; color: #9a3412; }}
      .row {{ display: flex; gap: 12px; align-items: center; }}
      .row input[type="checkbox"] {{ width: 18px; height: 18px; }}
      button {{
        background: #0f172a; color: #fff; border: 0; padding: 12px 18px;
        border-radius: 8px; font-weight: 600; cursor: pointer;
      }}
      footer {{ font-size: 12px; color: #666; margin-top: 10px; }}
      code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 6px; }}
    </style>
  </head>
  <body>
    <header>
      <h1>nanobot Settings</h1>
      <p>Configure API keys, models, and chat channels.</p>
    </header>
    <main>
      {notice}
      {write_note}
      {priority_note}
      <div class="card">
        <form method="post" action="/config">
          <div class="grid">
            <div>
              <label for="model">Model</label>
              <input id="model" name="model" type="text" value="{_escape(cfg.agents.defaults.model)}" />
              <div class="hint">Example: meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo</div>
            </div>
            <div>
              <label for="brave_api_key">Brave Search API Key</label>
              <input id="brave_api_key" name="brave_api_key" type="password" placeholder="{('set' if brave_set else 'not set')}" />
              <div class="hint">Leave blank to keep current value.</div>
            </div>
          </div>

          <div class="card" style="margin-top:16px;">
            <h3>Together AI</h3>
            <div class="grid">
              <div>
                <label for="together_api_key">API Key</label>
                <input id="together_api_key" name="together_api_key" type="password" placeholder="{('set' if together_set else 'not set')}" />
                <div class="hint">Leave blank to keep current value.</div>
              </div>
              <div>
                <label for="together_api_base">API Base (optional)</label>
                <input id="together_api_base" name="together_api_base" type="text" value="{_escape(cfg.providers.together.api_base or '')}" />
                <div class="hint">Default: https://api.together.xyz/v1</div>
              </div>
            </div>
          </div>

          <div class="card">
            <h3>OpenRouter</h3>
            <div class="grid">
              <div>
                <label for="openrouter_api_key">API Key</label>
                <input id="openrouter_api_key" name="openrouter_api_key" type="password" placeholder="{('set' if openrouter_set else 'not set')}" />
                <div class="hint">Leave blank to keep current value.</div>
              </div>
              <div>
                <label for="openrouter_api_base">API Base (optional)</label>
                <input id="openrouter_api_base" name="openrouter_api_base" type="text" value="{_escape(cfg.providers.openrouter.api_base or '')}" />
                <div class="hint">Default: https://openrouter.ai/api/v1</div>
              </div>
            </div>
          </div>

          <div class="card">
            <h3>Telegram</h3>
            <div class="row">
              <input id="telegram_enabled" name="telegram_enabled" type="checkbox" {'checked' if cfg.channels.telegram.enabled else ''} />
              <label for="telegram_enabled">Enable Telegram</label>
            </div>
            <div class="grid" style="margin-top:12px;">
              <div>
                <label for="telegram_token">Bot Token</label>
                <input id="telegram_token" name="telegram_token" type="password" placeholder="{('set' if telegram_set else 'not set')}" />
                <div class="hint">Leave blank to keep current value.</div>
              </div>
              <div>
                <label for="telegram_allow_from">Allowed Users (comma-separated)</label>
                <input id="telegram_allow_from" name="telegram_allow_from" type="text" value="{_escape(allow_from)}" />
              </div>
            </div>
          </div>

          <div class="card">
            <h3>WhatsApp</h3>
            <div class="row">
              <input id="whatsapp_enabled" name="whatsapp_enabled" type="checkbox" {'checked' if cfg.channels.whatsapp.enabled else ''} />
              <label for="whatsapp_enabled">Enable WhatsApp</label>
            </div>
          </div>

          <button type="submit">Save Settings</button>
          <footer>
            Config path: <code>{_escape(str(cfg_path))}</code>
          </footer>
        </form>
      </div>
    </main>
  </body>
</html>
"""

    def _update_config(fields: dict[str, list[str]]) -> None:
        cfg = load_config()

        model = _get_field(fields, "model")
        if model:
            cfg.agents.defaults.model = model

        brave_api_key = _get_field(fields, "brave_api_key")
        if brave_api_key:
            cfg.tools.web.search.api_key = brave_api_key

        together_api_key = _get_field(fields, "together_api_key")
        if together_api_key:
            cfg.providers.together.api_key = together_api_key

        together_api_base = _get_field(fields, "together_api_base")
        cfg.providers.together.api_base = together_api_base or None

        openrouter_api_key = _get_field(fields, "openrouter_api_key")
        if openrouter_api_key:
            cfg.providers.openrouter.api_key = openrouter_api_key

        openrouter_api_base = _get_field(fields, "openrouter_api_base")
        cfg.providers.openrouter.api_base = openrouter_api_base or None

        telegram_enabled = "telegram_enabled" in fields
        cfg.channels.telegram.enabled = telegram_enabled

        telegram_token = _get_field(fields, "telegram_token")
        if telegram_token:
            cfg.channels.telegram.token = telegram_token

        allow_from_raw = _get_field(fields, "telegram_allow_from")
        cfg.channels.telegram.allow_from = [
            item for item in (x.strip() for x in allow_from_raw.split(",")) if item
        ]

        whatsapp_enabled = "whatsapp_enabled" in fields
        cfg.channels.whatsapp.enabled = whatsapp_enabled

        save_config(cfg)
        if _is_true(os.getenv("NANOBOT_RESTART_ON_SAVE", "0")):
            console.print("[yellow]Restarting nanobot to apply settings...[/yellow]")
            # Exit the process to let Railway (or another supervisor) restart the service.
            import os as _os
            _os._exit(0)

    def start_web_server(host: str, web_port: int) -> ThreadingHTTPServer | None:
        class WebHandler(BaseHTTPRequestHandler):
            def _send_text(self, text: str, status: int = 200) -> None:
                body = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, html_text: str, status: int = 200) -> None:
                body = html_text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> str:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return ""
                return self.rfile.read(length).decode("utf-8", errors="ignore")

            def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                path = urlparse(self.path).path
                if path in ("/health", "/healthz", "/ready"):
                    self._send_text("ok", 200)
                    return
                if path in ("/", "/ui"):
                    query = parse_qs(urlparse(self.path).query)
                    saved = "saved" in query
                    error = query.get("error", [None])[0]
                    self._send_html(_render_settings_page(saved=saved, error=error))
                    return
                self._send_text("not found", 404)

            def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                path = urlparse(self.path).path
                if path in ("/config", "/"):
                    try:
                        body = self._read_body()
                        fields = parse_qs(body, keep_blank_values=True)
                        _update_config(fields)
                        self.send_response(303)
                        self.send_header("Location", "/?saved=1")
                        self.end_headers()
                    except Exception as exc:
                        self._send_html(_render_settings_page(error=str(exc)), 400)
                    return
                self._send_text("not found", 404)

            def log_message(self, format: str, *args) -> None:  # noqa: A002 - matches base signature
                if os.getenv("NANOBOT_HTTP_LOG", "") == "1":
                    super().log_message(format, *args)

        class WebServer(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        try:
            server = WebServer((host, web_port), WebHandler)
        except OSError as exc:
            console.print(
                f"[yellow]Warning: Web server failed to start on {host}:{web_port}: {exc}[/yellow]"
            )
            return None

        thread = Thread(target=server.serve_forever, name="nanobot-web", daemon=True)
        thread.start()
        console.print(f"[green]✓[/green] Web UI: http://{host}:{web_port}/")
        return server

    http_enabled = os.getenv("NANOBOT_HTTP_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
    web_server = start_web_server(config.gateway.host, port) if http_enabled else None
    
    # Create components
    bus = MessageBus()
    
    # Create provider (supports OpenRouter, Anthropic, OpenAI)
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    
    if not api_key:
        console.print("[yellow]Warning: No API key configured. Web UI is available for setup.[/yellow]")
        console.print("Set one in ~/.nanobot/config.json under providers.together.apiKey or providers.openrouter.apiKey")

        async def run_without_agent():
            try:
                while True:
                    await asyncio.sleep(3600)
            except KeyboardInterrupt:
                console.print("\nShutting down...")
            finally:
                if web_server:
                    web_server.shutdown()
                    web_server.server_close()

        asyncio.run(run_without_agent())
        return
    
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model,
        litellm_settings=getattr(config, "litellm_settings", None),
    )
    
    # Create agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None
    )
    
    # Create cron service
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}"
        )
        # Optionally deliver to channel
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "whatsapp",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path, on_job=on_cron_job)
    
    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")
    
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True
    )
    
    # Create channel manager
    channels = ChannelManager(config, bus)
    
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    console.print(f"[green]✓[/green] Heartbeat: every 30m")
    
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
        finally:
            if web_server:
                web_server.shutdown()
                web_server.server_close()
    
    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    
    config = load_config()
    
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    
    if not api_key:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)
    
    bus = MessageBus()
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model,
        litellm_settings=getattr(config, "litellm_settings", None),
    )
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        brave_api_key=config.tools.web.search.api_key or None
    )
    
    if message:
        # Single message mode
        async def run_once():
            response = await agent_loop.process_direct(message, session_id)
            console.print(f"\n{__logo__} {response}")
        
        asyncio.run(run_once())
    else:
        # Interactive mode
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)\n")
        
        async def run_interactive():
            while True:
                try:
                    user_input = console.input("[bold blue]You:[/bold blue] ")
                    if not user_input.strip():
                        continue
                    
                    response = await agent_loop.process_direct(user_input, session_id)
                    console.print(f"\n{__logo__} {response}\n")
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break
        
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
    table.add_column("Bridge URL", style="yellow")
    
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )
    
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
    pkg_bridge = Path(__file__).parent / "bridge"  # nanobot/bridge (installed)
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
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000))
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
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
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
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path
    from nanobot.utils.helpers import get_workspace_path
    
    config_path = get_config_path()
    workspace = get_workspace_path()
    
    console.print(f"{__logo__} nanobot Status\n")
    
    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")
    
    if config_path.exists():
        config = load_config()
        console.print(f"Model: {config.agents.defaults.model}")
        
        # Check API keys
        has_openrouter = bool(config.providers.openrouter.api_key)
        has_anthropic = bool(config.providers.anthropic.api_key)
        has_openai = bool(config.providers.openai.api_key)
        has_gemini = bool(config.providers.gemini.api_key)
        has_vllm = bool(config.providers.vllm.api_base)
        
        console.print(f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}")
        console.print(f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}")
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        vllm_status = f"[green]✓ {config.providers.vllm.api_base}[/green]" if has_vllm else "[dim]not set[/dim]"
        console.print(f"vLLM/Local: {vllm_status}")


if __name__ == "__main__":
    app()
