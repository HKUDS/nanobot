"""
Custom command: provider switcher
Commands: /providers, /switch, /add-provider

Register with: register(CommandRouter)
"""

from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandRouter


def register(router: CommandRouter) -> None:
    """Register custom provider management commands."""
    router.exact("/providers", cmd_providers)
    router.prefix("/switch ", cmd_switch)
    router.prefix("/add-provider ", cmd_add_provider)


def _get_runtime_config():
    """Load the current runtime config (Config type)."""
    from nanobot.config.loader import load_config
    return load_config()


def _get_provider_list(config):
    """Get list of (name, has_config, is_current) tuples."""
    current_provider = config.agents.defaults.provider
    all_configured = set(config.providers.model_dump().keys())

    result = []
    for name in sorted(all_configured):
        if name.startswith("_"):
            continue
        p = getattr(config.providers, name, None)
        has_config = p and (getattr(p, "api_key", None) or getattr(p, "api_base", None))
        if not has_config:
            continue
        is_current = (name == current_provider)
        result.append((name, p, is_current))

    # Sort: current provider first
    result.sort(key=lambda x: (0 if x[2] else 1, x[0]))
    return result


def _get_host(api_base: str | None) -> str:
    """Extract hostname from api_base for display."""
    if not api_base:
        return "unconfigured"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(api_base)
        return parsed.hostname or api_base[:40]
    except Exception:
        return api_base[:40]


def _save_config(config) -> None:
    """Persist config using nanobot's built-in save_config."""
    from nanobot.config.loader import save_config as nanobot_save
    nanobot_save(config)


def _reply(ctx, content: str) -> OutboundMessage:
    """Build a reply OutboundMessage from the command context."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_providers(ctx) -> OutboundMessage:
    """List all configured providers and mark the active one."""
    config = _get_runtime_config()
    providers = _get_provider_list(config)

    if not providers:
        return _reply(ctx,
            "[none] No providers configured\n\nUse: /add-provider <name> <api_base> <api_key>",
        )

    lines = ["Configured Providers:"]
    for name, p, is_current in providers:
        marker = "[*]" if is_current else "[ ]"
        key_status = "yes" if getattr(p, "api_key", None) else "no"
        host = _get_host(getattr(p, "api_base", None))
        lines.append(f"  {marker} {name} -- {host} (key: {key_status})")

    lines.append("")
    lines.append("Tip: /switch <name> to switch, /add-provider <name> <url> to add")

    return _reply(ctx, "\n".join(lines))


async def cmd_switch(ctx) -> OutboundMessage:
    """Switch to a specific provider."""
    parts = ctx.msg.content.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return _reply(ctx,
            "Usage: /switch <provider_name>\n\nUse /providers to see available providers",
        )

    name = parts[1].strip()
    config = _get_runtime_config()
    providers = _get_provider_list(config)
    available = [n for n, _, _ in providers]

    if name not in available:
        return _reply(ctx,
            f"Error: provider \"{name}\" is not configured\n\nAvailable: {', '.join(available)}",
        )

    # Get current model name (strip provider prefix if any)
    current_model = config.agents.defaults.model
    if "/" in current_model:
        model_name = current_model.split("/", 1)[1]
    else:
        model_name = current_model

    # Update config: use provider field to control which provider
    config.agents.defaults.provider = name
    config.agents.defaults.model = model_name

    # Save to config file
    _save_config(config)

    return _reply(ctx,
        f"Switched to {name}\n   model: {model_name}\n\nRequires /restart to take effect",
    )


async def cmd_add_provider(ctx) -> OutboundMessage:
    """Add a new custom provider."""
    parts = ctx.msg.content.split()
    # /add-provider <name> <api_base> [api_key]
    if len(parts) < 4:
        return _reply(ctx,
            "Usage: /add-provider <name> <api_base> [api_key]\n\nExample: /add-provider myapi https://api.example.com/v1 sk-xxx",
        )

    name = parts[1]
    api_base = parts[2]
    api_key = parts[3] if len(parts) > 3 else ""

    # Validate name (alphanumeric + underscore only)
    import re
    if not re.match(r"^[a-zA-Z0-9_]+$", name):
        return _reply(ctx, "Error: name must contain only letters, digits, and underscores")

    config = _get_runtime_config()

    # Check if provider already exists and has config
    existing = getattr(config.providers, name, None)
    if existing and (getattr(existing, "api_key", None) or getattr(existing, "api_base", None)):
        return _reply(ctx,
            f"Provider \"{name}\" already exists. Use /switch {name} to activate it",
        )

    # Create provider config
    from nanobot.config.schema import ProviderConfig
    provider_config = ProviderConfig(api_key=api_key, api_base=api_base)

    # Set on providers object
    setattr(config.providers, name, provider_config)

    # Save to config file
    _save_config(config)

    return _reply(ctx,
        f"Added provider: {name}\n   api_base: {api_base}\n\nUse /switch {name} to activate",
    )
