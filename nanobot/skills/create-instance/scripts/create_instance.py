#!/usr/bin/env python3
"""Create a new nanobot instance with a dedicated config and workspace.

Usage:
    create_instance.py --name <name> --channel <channel> [--model <model>] [--config-dir <dir>]

Examples:
    create_instance.py --name telegram-bot --channel telegram
    create_instance.py --name discord-bot --channel discord --model deepseek/deepseek-chat
    create_instance.py --name my-bot --channel telegram --config-dir ~/.nanobot-custom
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from pathlib import Path


def _validate_name(name: str) -> str:
    """Normalize and validate instance name."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    if not name:
        print("[ERROR] Instance name must contain at least one letter or digit.", file=sys.stderr)
        sys.exit(1)
    if len(name) > 64:
        print(f"[ERROR] Instance name too long ({len(name)} chars, max 64).", file=sys.stderr)
        sys.exit(1)
    return name


def _get_available_channels() -> list[str]:
    """Get list of available channel names without importing channel classes."""
    from nanobot.channels.registry import discover_channel_names

    return discover_channel_names()


def _run_onboard(config_path: Path, workspace: Path) -> None:
    """Create skeleton config + workspace using nanobot's programmatic API."""
    from nanobot.cli.commands import _onboard_plugins
    from nanobot.config.loader import save_config, set_config_path
    from nanobot.config.paths import get_workspace_path
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import sync_workspace_templates

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    set_config_path(config_path)
    save_config(config, config_path)
    _onboard_plugins(config_path)

    workspace_path = get_workspace_path(config.workspace_path)
    if not workspace_path.exists():
        workspace_path.mkdir(parents=True, exist_ok=True)
    sync_workspace_templates(workspace_path)


def _patch_config(
    config_path: Path,
    *,
    channel: str,
    workspace: Path,
    model: str | None,
    inherit_config_path: Path | None = None,
) -> dict:
    """Patch the generated config: enable channel, set workspace, optionally set model."""
    data = json.loads(config_path.read_text(encoding="utf-8"))

    # Inherit providers and model from current instance
    if inherit_config_path and inherit_config_path.exists():
        try:
            src = json.loads(inherit_config_path.read_text(encoding="utf-8"))

            # Inherit providers (API keys, api_base, etc.)
            src_providers = src.get("providers", {})
            if src_providers:
                data.setdefault("providers", {})
                for key, val in src_providers.items():
                    if isinstance(val, dict) and val.get("apiKey"):
                        data["providers"][key] = val

            # Inherit model if not explicitly overridden
            if not model:
                parent_model = src.get("agents", {}).get("defaults", {}).get("model")
                if parent_model:
                    model = parent_model

        except Exception as exc:
            print(f"[WARN] Could not inherit from {inherit_config_path}: {exc}", file=sys.stderr)

    # Set workspace and model
    data.setdefault("agents", {}).setdefault("defaults", {})
    data["agents"]["defaults"]["workspace"] = str(workspace)
    if model:
        data["agents"]["defaults"]["model"] = model

    # Enable the target channel
    channels = data.setdefault("channels", {})
    if channel in channels and isinstance(channels[channel], dict):
        channels[channel]["enabled"] = True
    else:
        channels[channel] = {"enabled": True}

    # Auto-assign ports if defaults are already in use
    _assign_free_ports(data)

    # Validate with Pydantic, then save
    from nanobot.config.schema import Config

    Config.model_validate(data)
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _find_free_port(start: int, host: str = "127.0.0.1", max_tries: int = 100) -> int:
    """Find the first free port starting from `start`."""
    for port in range(start, start + max_tries):
        if not _is_port_in_use(port, host):
            return port
    # OS-level fallback: ask the kernel for an ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _assign_free_ports(data: dict) -> None:
    """If default gateway or API ports are in use, assign free ones."""
    from nanobot.config.schema import ApiConfig, GatewayConfig

    defaults = [
        ("gateway", GatewayConfig()),
        ("api", ApiConfig()),
    ]
    for key, default_cfg in defaults:
        section = data.setdefault(key, {})
        port = section.get("port", default_cfg.port)
        host = section.get("host", default_cfg.host)
        if _is_port_in_use(port, host):
            section["port"] = _find_free_port(port + 1, host)


def _get_channel_required_fields(channel: str) -> list[str]:
    """Inspect a channel's default config and list fields that are empty strings."""
    try:
        from nanobot.channels.registry import load_channel_class

        cls = load_channel_class(channel)
        default = cls.default_config()
        return sorted(k for k, v in default.items() if isinstance(v, str) and v == "" and k != "enabled")
    except Exception as exc:
        print(f"[WARN] Could not inspect channel '{channel}' defaults: {exc}", file=sys.stderr)
        return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a new nanobot instance.",
    )
    parser.add_argument("--name", required=True, help="Instance name (e.g. telegram-bot)")
    parser.add_argument("--channel", required=True, help="Channel type (e.g. telegram, discord)")
    parser.add_argument("--model", default=None, help="LLM model (default: same as current instance)")
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Config directory (default: ~/.nanobot-{name})",
    )
    parser.add_argument(
        "--inherit-config",
        default=None,
        help="Path to current instance's config.json to copy API keys from",
    )
    args = parser.parse_args()

    # Validate name
    name = _validate_name(args.name)

    # Validate channel
    available = _get_available_channels()
    if args.channel not in available:
        print(f"[ERROR] Unknown channel: {args.channel}", file=sys.stderr)
        print(f"Available channels: {', '.join(sorted(available))}", file=sys.stderr)
        sys.exit(1)

    # Resolve paths
    home = Path.home()
    config_dir = Path(args.config_dir).expanduser().resolve() if args.config_dir else home / f".nanobot-{name}"
    config_path = config_dir / "config.json"
    workspace = config_dir / "workspace"

    # Check for duplicate
    if config_path.exists():
        print(f"[ERROR] Config already exists at {config_path}", file=sys.stderr)
        print("Delete it first or use a different --config-dir.", file=sys.stderr)
        sys.exit(1)

    print(f"Creating instance '{name}'...")
    print(f"  Config dir: {config_dir}")
    print(f"  Workspace:  {workspace}")
    print(f"  Channel:    {args.channel}")
    if args.model:
        print(f"  Model:      {args.model}")

    # Run onboard
    _run_onboard(config_path, workspace)

    # Patch config
    inherit_path = Path(args.inherit_config).expanduser().resolve() if args.inherit_config else None
    _patch_config(
        config_path,
        channel=args.channel,
        workspace=workspace,
        model=args.model,
        inherit_config_path=inherit_path,
    )

    # Report
    print(f"\n[OK] Instance '{name}' created successfully.")
    print(f"  Config: {config_path}")
    print(f"  Workspace: {workspace}")

    # List fields the user needs to fill in
    required_fields = _get_channel_required_fields(args.channel)
    if required_fields:
        print(f"\n[IMPORTANT] Edit {config_path} and fill in these fields:")
        for field in required_fields:
            print(f"  - channels.{args.channel}.{field}")

    print(f"\nTo start the instance:")
    print(f"  nanobot gateway --config {config_path}")


if __name__ == "__main__":
    main()
