"""Load and activate locally installed Agent Plugin packages."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import cast

from loguru import logger
from pydantic import ValidationError

from nanobot.agent.skills import parse_skill_metadata, valid_skill_metadata
from nanobot.config.loader import get_config_path
from nanobot.config.schema import MCPServerConfig

AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AGENT_PLUGIN_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

_PLUGIN_NAME = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_MCP_SERVER_FIELDS = {"type", "command", "args", "env", "cwd"}
_MAX_LOGO_BYTES = 256 * 1024
_SKILL_CACHE: dict[tuple[Path, Path], tuple[tuple[str, Path], ...]] = {}


@dataclass(frozen=True)
class AgentPlugin:
    """A validated, locally installed Agent Plugins v1 package."""

    name: str
    root: Path
    description: str
    repository: str
    display_name: str
    category: str
    accent_color: str | None
    logo: str | None
    permissions: tuple[str, ...]
    mcp_servers: tuple[str, ...] = ()
    enabled: bool = False


def _installed_plugins(workspace: Path) -> list[AgentPlugin]:
    """Return installed packages found under ``<workspace>/plugins/*``."""
    workspace = workspace.expanduser().resolve()
    root = _contained(workspace / "plugins", workspace, directory=True)
    if root is None:
        return []
    plugins: dict[str, AgentPlugin | None] = {}
    for candidate in _children(root, "Agent Plugins directory"):
        plugin_root = _contained(candidate, root, directory=True)
        if plugin_root is None:
            continue
        plugin = _load_manifest(plugin_root)
        if plugin is not None:
            if plugin.name in plugins:
                logger.warning("Ignoring duplicate Agent Plugin identity '{}'", plugin.name)
                plugins[plugin.name] = None
            else:
                plugins[plugin.name] = plugin
    return [plugin for plugin in plugins.values() if plugin is not None]


def enabled_agent_plugin_skills(workspace: Path) -> list[tuple[str, Path]]:
    """Verify and return skills from plugins the user has explicitly enabled."""
    skills = [
        skill
        for plugin in _installed_plugins(workspace)
        if _enabled(workspace, plugin)
        for skill in _discover_plugin_skills(plugin.name, plugin.root)
    ]
    _SKILL_CACHE[_skill_cache_key(workspace)] = tuple(skills)
    return skills


def enabled_agent_plugin_skill_dirs(workspace: Path) -> tuple[Path, ...]:
    """Return the last verified skill roots, verifying once on a cache miss."""
    key = _skill_cache_key(workspace)
    skills = _SKILL_CACHE.get(key)
    if skills is None:
        skills = tuple(enabled_agent_plugin_skills(workspace))
    return tuple(path.parent for _name, path in skills)


def _skill_cache_key(workspace: Path) -> tuple[Path, Path]:
    return (
        workspace.expanduser().resolve(),
        get_config_path().expanduser().resolve(),
    )


def _invalidate_skill_cache(workspace: Path) -> None:
    _SKILL_CACHE.pop(_skill_cache_key(workspace), None)


def _load_manifest(plugin_root: Path) -> AgentPlugin | None:
    payload = _read_object(plugin_root / "plugin.json", plugin_root)
    if payload is None:
        return None
    if payload.get("$schema") != AGENT_PLUGIN_SCHEMA:
        return None
    name = payload.get("name")
    if (
        not isinstance(name, str)
        or len(name) > 64
        or _PLUGIN_NAME.fullmatch(name) is None
    ):
        logger.warning("Ignoring Agent Plugin manifest in '{}': invalid name", plugin_root)
        return None
    extension = payload.get("extensions")
    extension_payload = cast(dict[str, object], extension) if isinstance(extension, dict) else {}
    nanobot_value = extension_payload.get("dev.nanobot")
    nanobot = cast(dict[str, object], nanobot_value) if isinstance(nanobot_value, dict) else {}
    return AgentPlugin(
        name=name,
        root=plugin_root,
        description=_string(payload.get("description")),
        repository=_string(payload.get("repository")),
        display_name=_string(nanobot.get("displayName")) or name,
        category=_string(nanobot.get("category")) or "Plugin",
        accent_color=_accent_color(nanobot.get("accentColor")),
        logo=_plugin_logo(nanobot.get("logo"), plugin_root),
        permissions=_string_tuple(nanobot.get("permissions")),
    )


def agent_plugin_mcp_servers(
    workspace: Path,
    configured: dict[str, MCPServerConfig] | None = None,
) -> dict[str, MCPServerConfig]:
    """Merge explicitly enabled plugin MCP servers with user configuration.

    User configuration wins on the unlikely event of a namespaced collision.
    """
    servers: dict[str, MCPServerConfig] = {}
    for plugin in _installed_plugins(workspace):
        if not _enabled(workspace, plugin):
            continue
        plugin_servers = _plugin_mcp_servers(workspace, plugin)
        for name, server in plugin_servers.items():
            # ``--`` cannot occur in a valid plugin identity, so multi-server
            # namespaces cannot collide with a single-server plugin name.
            host_name = plugin.name if len(plugin_servers) == 1 else f"{plugin.name}--{name}"
            servers[host_name] = server
    configured = configured or {}
    if collisions := servers.keys() & configured.keys():
        logger.warning("Configured MCP servers override Agent Plugins: {}", ", ".join(sorted(collisions)))
    return servers | configured


def discover_agent_plugins(workspace: Path) -> list[AgentPlugin]:
    """Return component and lifecycle state for discovered plugins."""
    return [
        replace(
            plugin,
            mcp_servers=tuple(sorted(_plugin_mcp_servers(workspace, plugin))),
            enabled=_enabled(workspace, plugin),
        )
        for plugin in _installed_plugins(workspace)
    ]


def set_agent_plugin_enabled(workspace: Path, name: str, enabled: bool) -> None:
    """Enable or disable one installed plugin."""
    plugin = next((item for item in _installed_plugins(workspace) if item.name == name), None)
    if plugin is None:
        raise ValueError(f"unknown Agent Plugin '{name}'")
    data = _plugin_data_dir(workspace, plugin.name, create=True)
    marker = data / "enabled"
    if enabled:
        activation = _activation_marker(plugin)
        if activation is None:
            raise RuntimeError(f"Agent Plugin '{name}' changed while it was being enabled")
        marker.write_text(activation, encoding="utf-8")
        marker.chmod(0o600)
    else:
        marker.unlink(missing_ok=True)
    _invalidate_skill_cache(workspace)


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_tuple(value: object) -> tuple[str, ...]:
    items = cast(list[object], value) if isinstance(value, list) else []
    return tuple(item.strip() for item in items if isinstance(item, str) and item.strip())


def _accent_color(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else None


def _plugin_logo(value: object, plugin_root: Path) -> str | None:
    """Resolve nanobot's optional packaged logo extension."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith("./"):
        logger.warning("Ignoring invalid Agent Plugin logo in '{}'", plugin_root)
        return None
    logo = _contained(plugin_root / value[2:], plugin_root)
    try:
        data = logo.read_bytes() if logo is not None else b""
        suffix = logo.suffix.lower() if logo is not None else ""
        if len(data) <= _MAX_LOGO_BYTES and (
            suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n")
            or suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff")
            or suffix == ".webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
        ):
            mime = "jpeg" if suffix in {".jpg", ".jpeg"} else suffix[1:]
            return f"data:image/{mime};base64,{base64.b64encode(data).decode('ascii')}"
    except OSError:
        pass
    logger.warning("Ignoring invalid Agent Plugin logo in '{}'", plugin_root)
    return None


def _plugin_mcp_servers(workspace: Path, plugin: AgentPlugin) -> dict[str, MCPServerConfig]:
    payload = _read_object(plugin.root / "mcp.json", plugin.root)
    if payload is None:
        return {}
    raw_servers = payload.get("mcpServers")
    if (
        payload.keys() != {"$schema", "mcpServers"}
        or payload.get("$schema") != AGENT_PLUGIN_MCP_SCHEMA
        or not isinstance(raw_servers, dict)
    ):
        logger.warning("Ignoring invalid MCP component for Agent Plugin '{}'", plugin.name)
        return {}

    data = _plugin_data_dir(workspace, plugin.name, create=True)
    servers: dict[str, MCPServerConfig] = {}
    for name, raw in cast(dict[str, object], raw_servers).items():
        if not name or len(name) > 128 or any(ord(char) < 32 for char in name):
            logger.warning("Ignoring invalid MCP server name in Agent Plugin '{}'", plugin.name)
            continue
        server = _plugin_mcp_server(raw, plugin.root, data)
        if server is None:
            logger.warning("Ignoring invalid MCP server '{}' in Agent Plugin '{}'", name, plugin.name)
            continue
        servers[name] = server
    return servers


def _plugin_mcp_server(raw: object, root: Path, data: Path) -> MCPServerConfig | None:
    if not isinstance(raw, dict):
        return None
    payload = cast(dict[str, object], raw)
    if payload.keys() - _MCP_SERVER_FIELDS:
        return None
    try:
        server = MCPServerConfig.model_validate(payload)
    except ValidationError:
        return None
    command = _stdio_command(server.command, root)
    cwd = _stdio_cwd(payload.get("cwd"), root, data)
    if server.type != "stdio" or command is None or cwd is None:
        return None
    if {"PLUGIN_ROOT", "PLUGIN_DATA"} & server.env.keys():
        return None
    return server.model_copy(
        update={
            "command": command,
            "args": [_expand(item, root, data) for item in server.args],
            "env": {
                **{key: _expand(value, root, data) for key, value in server.env.items()},
                "PYTHONDONTWRITEBYTECODE": "1",
                "PLUGIN_ROOT": str(root),
                "PLUGIN_DATA": str(data),
            },
            "cwd": str(cwd),
        }
    )


def _stdio_command(value: object, root: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("./"):
        executable = _contained(root / value[2:], root)
        return str(executable) if executable is not None else None
    if any(char.isspace() for char in value) or "/" in value or "\\" in value:
        return None
    return value


def _stdio_cwd(value: object, root: Path, data: Path) -> Path | None:
    if value is None:
        return root
    if not isinstance(value, str):
        return None
    if value.startswith("./"):
        return _contained(root / value[2:], root, directory=True)
    for placeholder, base in (("${PLUGIN_ROOT}", root), ("${PLUGIN_DATA}", data)):
        if value == placeholder or value.startswith(f"{placeholder}/"):
            relative = value[len(placeholder):].lstrip("/")
            candidate = (base / relative).resolve()
            if not candidate.is_relative_to(base):
                return None
            if base == data:
                candidate.mkdir(parents=True, exist_ok=True)
                candidate.chmod(0o700)
            return candidate if candidate.is_dir() else None
    return None


def _expand(value: str, root: Path, data: Path) -> str:
    return value.replace("${PLUGIN_ROOT}", str(root)).replace("${PLUGIN_DATA}", str(data))


def _plugin_data_dir(workspace: Path, name: str, *, create: bool) -> Path:
    workspace_id = sha256(str(workspace.expanduser().resolve()).encode()).hexdigest()[:12]
    current = get_config_path().expanduser().resolve().parent
    for segment in ("plugin-data", workspace_id, name):
        path = current / segment
        if create:
            path.mkdir(parents=True, exist_ok=True)
        try:
            resolved = path.resolve(strict=create)
        except OSError as exc:
            raise RuntimeError("Agent Plugin data directory is unavailable") from exc
        if not resolved.is_relative_to(current):
            raise RuntimeError("Agent Plugin data directory escapes its parent")
        if create:
            resolved.chmod(0o700)
        current = resolved
    return current


def _enabled(workspace: Path, plugin: AgentPlugin) -> bool:
    marker = _plugin_data_dir(workspace, plugin.name, create=False) / "enabled"
    try:
        if not marker.is_file():
            return False
        current = marker.read_text(encoding="utf-8")
        activation = _activation_marker(plugin)
        if activation is None:
            marker.unlink(missing_ok=True)
            _invalidate_skill_cache(workspace)
            return False
        if current == activation:
            return True
        if current == str(plugin.root):
            marker.write_text(activation, encoding="utf-8")
            marker.chmod(0o600)
            return True
        marker.unlink(missing_ok=True)
        _invalidate_skill_cache(workspace)
        return False
    except OSError:
        _invalidate_skill_cache(workspace)
        return False


def _activation_marker(plugin: AgentPlugin) -> str | None:
    """Bind activation to one immutable package snapshot."""
    digest = sha256()
    try:
        for candidate in sorted(plugin.root.rglob("*")):
            relative = candidate.relative_to(plugin.root).as_posix()
            digest.update(relative.encode())
            if candidate.is_symlink():
                digest.update(b"\0link\0")
                digest.update(candidate.readlink().as_posix().encode())
            elif candidate.is_file():
                digest.update(b"\0file\0")
                digest.update(candidate.read_bytes())
            elif candidate.is_dir():
                digest.update(b"\0dir\0")
            else:
                return None
            digest.update(b"\0")
    except OSError:
        return None
    return json.dumps(
        {"fingerprint": digest.hexdigest(), "root": str(plugin.root)},
        separators=(",", ":"),
        sort_keys=True,
    )


def _discover_plugin_skills(plugin_name: str, plugin_root: Path) -> list[tuple[str, Path]]:
    skills_root = _contained(plugin_root / "skills", plugin_root, directory=True)
    if skills_root is None:
        return []

    skills: list[tuple[str, Path]] = []
    for candidate in _children(skills_root, f"Agent Plugin '{plugin_name}' skills"):
        skill_root = _contained(candidate, skills_root, directory=True)
        if skill_root is None:
            continue
        skill_file = _contained(skill_root / "SKILL.md", plugin_root)
        if skill_file is None:
            continue
        try:
            metadata = parse_skill_metadata(skill_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            metadata = None
        if metadata is None or not valid_skill_metadata(metadata, candidate.name):
            logger.warning("Ignoring Agent Plugin '{}' skill '{}': invalid metadata", plugin_name, candidate.name)
            continue
        skills.append((candidate.name, skill_file))
    return skills


def _children(root: Path, label: str) -> list[Path]:
    try:
        return sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        logger.warning("Could not inspect {}: {}", label, exc)
        return []


def _contained(path: Path, root: Path, *, directory: bool = False) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    expected_kind = resolved.is_dir() if directory else resolved.is_file()
    return resolved if expected_kind and resolved.is_relative_to(root) else None


def _read_object(path: Path, root: Path) -> dict[str, object] | None:
    contained = _contained(path, root)
    if contained is None:
        return None
    try:
        value = cast(object, json.loads(contained.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid Agent Plugin component '{}': {}", contained, exc)
        return None
    return cast(dict[str, object], value) if isinstance(value, dict) else None
