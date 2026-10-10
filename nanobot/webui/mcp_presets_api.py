"""MCP preset helpers for the WebUI settings and message surfaces."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import urllib.parse
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping, cast

from nanobot.agent.plugins import (
    AgentPlugin,
    discover_agent_plugins,
    set_agent_plugin_enabled,
)
from nanobot.agent.tools.mcp_oauth import (
    delete_mcp_oauth_credentials,
    mcp_oauth_has_credentials,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.apps.computer_use_native import CAPABILITY as CUA_NATIVE_CAPABILITY
from nanobot.apps.cua_driver import CAPABILITY as CUA_CAPABILITY
from nanobot.apps.cua_driver import PERMISSIONS_CAPABILITY as CUA_PERMISSIONS_CAPABILITY
from nanobot.apps.cua_driver import RECONNECT_CAPABILITY as CUA_RECONNECT_CAPABILITY
from nanobot.apps.cua_driver import SETUP_CAPABILITY as CUA_SETUP_CAPABILITY
from nanobot.apps.cua_driver import UNINSTALL_CAPABILITY as CUA_UNINSTALL_CAPABILITY
from nanobot.apps.cua_driver import UNINSTALL_RESET_CAPABILITY as CUA_UNINSTALL_RESET_CAPABILITY
from nanobot.apps.cua_driver import CuaDriver, DriverError
from nanobot.apps.protocol import app_manifest, compact_dict
from nanobot.config.loader import load_config, resolve_config_env_vars, save_config
from nanobot.config.paths import get_config_path, get_runtime_subdir
from nanobot.config.schema import Config, MCPServerConfig
from nanobot.utils.helpers import ensure_dir

QueryParams = dict[str, list[str]]

if TYPE_CHECKING:
    from nanobot.agent.tools.mcp import MCPReload
    from nanobot.webui.settings_services import WebUISettingsConfig

_MCP_PRESET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.IGNORECASE)
_SECRET_QUERY_RE = re.compile(
    r"([?&](?:[^=&]*(?:api[_-]?key|token|secret|password|bearer)[^=&]*)=)[^&#\s]+",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"((?:api[_-]?key|token|secret|password|bearer)(?:[=:]|\s+))[^,\s'\"&]+",
    re.IGNORECASE,
)
_MCP_ATTACHMENT_KEYS = (
    "name",
    "display_name",
    "category",
    "transport",
    "logo_url",
    "brand_color",
    "status",
    "configured",
)
_DEFAULT_TEST_TIMEOUT = 20
_DEFAULT_CUSTOM_TIMEOUT = 30
_CUSTOM_ACTIONS = {"custom", "import", "import-cursor", "tools"}
_MCP_RUNTIME_STATUSES = {"connecting", "connected", "failed"}

McpRuntimeStatus = Callable[[], Mapping[str, str]]


class McpPresetError(Exception):
    """WebUI-facing MCP preset error."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class McpPresetField:
    name: str
    label: str
    target: tuple[Literal["env", "url_param", "arg", "header"], str]
    secret: bool = True
    required: bool = True
    env_var: str | None = None
    placeholder: str = ""


@dataclass(frozen=True)
class McpPreset:
    name: str
    display_name: str
    category: str
    description: str
    docs_url: str
    transport: Literal["stdio", "streamableHttp", "sse", "oauth"]
    install_supported: bool
    brand_domain: str
    brand_color: str
    server: MCPServerConfig | None = None
    fields: tuple[McpPresetField, ...] = ()
    requires: str = ""
    note: str = ""


def _favicon_url(domain: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


MCP_PRESETS: tuple[McpPreset, ...] = (
    McpPreset(
        name="cua-driver", display_name="Cua Driver", category="computer",
        description="Observe and operate the gateway computer through a locally installed desktop driver.",
        docs_url="https://cua.ai/docs/cua-driver/quickstart", transport="stdio",
        install_supported=True, brand_domain="cua.ai", brand_color="#64748B",
        requires="A graphical desktop and a vision-capable model",
        note="Install on the gateway computer. OS permissions require your confirmation.",
    ),
    McpPreset(
        name="browserbase",
        display_name="Browserbase",
        category="browser",
        description="Cloud browser automation through Browserbase's hosted MCP server.",
        docs_url="https://docs.browserbase.com/integrations/mcp/setup",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="browserbase.com",
        brand_color="#111827",
        requires="Browserbase API key",
        server=MCPServerConfig(
            type="streamableHttp",
            url="https://mcp.browserbase.com/mcp",
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="browserbase_api_key",
                label="Browserbase API key",
                target=("url_param", "browserbaseApiKey"),
                env_var="BROWSERBASE_API_KEY",
                placeholder="bb_live_...",
            ),
        ),
    ),
    McpPreset(
        name="playwright",
        display_name="Playwright",
        category="browser",
        description="Local browser inspection and automation with Playwright's MCP server.",
        docs_url="https://playwright.dev/docs/getting-started-mcp",
        transport="stdio",
        install_supported=True,
        brand_domain="playwright.dev",
        brand_color="#2EAD33",
        requires="Node.js and npx",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@playwright/mcp@latest"],
            tool_timeout=60,
        ),
    ),
    McpPreset(
        name="context7",
        display_name="Context7",
        category="docs",
        description="Fetch current library docs and code examples while the agent works.",
        docs_url="https://context7.com/docs/resources/all-clients",
        transport="stdio",
        install_supported=True,
        brand_domain="context7.com",
        brand_color="#111827",
        requires="Node.js and npx; API key optional",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@upstash/context7-mcp@latest"],
            tool_timeout=45,
        ),
        fields=(
            McpPresetField(
                name="context7_api_key",
                label="Context7 API key",
                target=("arg", "--api-key"),
                env_var="CONTEXT7_API_KEY",
                placeholder="ctx7_...",
                required=False,
            ),
        ),
        note="Works without a key for basic public docs; add a key for higher limits or private docs.",
    ),
    McpPreset(
        name="firecrawl",
        display_name="Firecrawl",
        category="web",
        description="Scrape, crawl, search, and extract web pages through Firecrawl's MCP server.",
        docs_url="https://docs.firecrawl.dev/use-cases/developers-mcp",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="firecrawl.dev",
        brand_color="#EB5E28",
        requires="Network access",
        server=MCPServerConfig(
            type="streamableHttp",
            url="https://mcp.firecrawl.dev/v2/mcp",
            tool_timeout=60,
        ),
        note=(
            "Uses Firecrawl Keyless through the hosted MCP endpoint. No API key is required for "
            "the built-in preset; use a custom MCP server URL if you want account-specific limits."
        ),
    ),
    McpPreset(
        name="parallel-search",
        display_name="Parallel Search",
        category="web",
        description="Search the web and fetch relevant page content through Parallel's hosted MCP server.",
        docs_url="https://docs.parallel.ai/integrations/mcp/search-mcp",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="parallel.ai",
        brand_color="#111827",
        requires="Network access",
        server=MCPServerConfig(
            type="streamableHttp",
            url="https://search.parallel.ai/mcp",
            tool_timeout=60,
            enabled_tools=["web_search", "web_fetch"],
        ),
        note="Free anonymous access for light use; no API key is required.",
    ),
    McpPreset(
        name="exa",
        display_name="Exa",
        category="web",
        description="Search the web and fetch clean page content through Exa's hosted MCP server.",
        docs_url="https://exa.ai/mcp",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="exa.ai",
        brand_color="#101010",
        requires="Network access",
        server=MCPServerConfig(
            type="streamableHttp",
            url="https://mcp.exa.ai/mcp",
            tool_timeout=45,
        ),
        note="Hosted Exa MCP endpoint currently does not require an API key.",
    ),
    McpPreset(
        name="microsoft-learn",
        display_name="Microsoft Learn",
        category="docs",
        description="Search and fetch Microsoft Learn documentation through Microsoft's hosted MCP server.",
        docs_url="https://learn.microsoft.com/en-us/training/support/mcp",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="learn.microsoft.com",
        brand_color="#0078D4",
        requires="Network access",
        server=MCPServerConfig(
            type="streamableHttp",
            url="https://learn.microsoft.com/api/mcp",
            tool_timeout=45,
        ),
        note="Public documentation only; no authentication required.",
    ),
    McpPreset(
        name="aws-docs",
        display_name="AWS Documentation",
        category="docs",
        description="Search AWS documentation and service guidance through AWS Labs' documentation MCP server.",
        docs_url="https://awslabs.github.io/mcp/servers/aws-documentation-mcp-server/",
        transport="stdio",
        install_supported=True,
        brand_domain="aws.amazon.com",
        brand_color="#FF9900",
        requires="uvx",
        server=MCPServerConfig(
            type="stdio",
            command="uvx",
            args=["awslabs.aws-documentation-mcp-server@latest"],
            env={"FASTMCP_LOG_LEVEL": "ERROR", "AWS_DOCUMENTATION_PARTITION": "aws"},
            tool_timeout=60,
        ),
    ),
    McpPreset(
        name="brave-search",
        display_name="Brave Search",
        category="web",
        description="Run web, news, image, video, and local search through Brave Search.",
        docs_url="https://www.npmjs.com/package/@brave/brave-search-mcp-server",
        transport="stdio",
        install_supported=True,
        brand_domain="brave.com",
        brand_color="#FB542B",
        requires="Node.js, npx, and Brave Search API key",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@brave/brave-search-mcp-server@latest", "--transport", "stdio"],
            tool_timeout=45,
        ),
        fields=(
            McpPresetField(
                name="brave_api_key",
                label="Brave Search API key",
                target=("env", "BRAVE_API_KEY"),
                env_var="BRAVE_API_KEY",
                placeholder="BSA...",
            ),
        ),
    ),
    McpPreset(
        name="postman",
        display_name="Postman",
        category="api",
        description="Inspect and manage Postman APIs, collections, and workspaces through the local MCP server.",
        docs_url="https://learning.postman.com/docs/developer/postman-api/postman-mcp-server/postman-mcp-local-server",
        transport="stdio",
        install_supported=True,
        brand_domain="postman.com",
        brand_color="#FF6C37",
        requires="Node.js, npx, and Postman API key",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@postman/postman-mcp-server@latest", "--full"],
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="postman_api_key",
                label="Postman API key",
                target=("env", "POSTMAN_API_KEY"),
                env_var="POSTMAN_API_KEY",
                placeholder="PMAK-...",
            ),
        ),
    ),
    McpPreset(
        name="figma",
        display_name="Figma",
        category="design",
        description="Read design context from Figma using the local Dev Mode MCP server.",
        docs_url="https://help.figma.com/hc/en-us/articles/32132100833559-Guide-to-the-Figma-MCP-server",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="figma.com",
        brand_color="#F24E1E",
        requires="Figma desktop app with MCP enabled",
        server=MCPServerConfig(
            type="streamableHttp",
            url="http://127.0.0.1:3845/mcp",
            tool_timeout=45,
        ),
        note="Requires Figma Desktop Dev Mode MCP to be running locally.",
    ),
    McpPreset(
        name="xmind",
        display_name="Xmind",
        category="productivity",
        description="Create, read, and edit cloud mind maps through Xmind.",
        docs_url="https://xmind.com/user-guide/xmind-mcp",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="xmind.com",
        brand_color="#F4B41A",
        requires="Xmind account",
        server=MCPServerConfig(
            type="streamableHttp",
            auth="oauth",
            url="https://app.xmind.com/api/mcp",
            tool_timeout=60,
        ),
        note="Connects securely in your browser with Xmind OAuth.",
    ),
    McpPreset(
        name="notion",
        display_name="Notion",
        category="productivity",
        description="Read and update your Notion workspace through Notion MCP.",
        docs_url="https://developers.notion.com/guides/mcp/get-started-with-mcp",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="notion.so",
        brand_color="#111111",
        requires="Notion account",
        server=MCPServerConfig(
            type="streamableHttp",
            auth="oauth",
            url="https://mcp.notion.com/mcp",
            tool_timeout=60,
        ),
        note="Connects securely in your browser with Notion OAuth.",
    ),
    McpPreset(
        name="linear",
        display_name="Linear",
        category="productivity",
        description="Find and manage Linear issues, projects, and comments.",
        docs_url="https://linear.app/docs/mcp",
        transport="streamableHttp",
        install_supported=True,
        brand_domain="linear.app",
        brand_color="#5E6AD2",
        requires="Linear account",
        server=MCPServerConfig(
            type="streamableHttp",
            auth="oauth",
            url="https://mcp.linear.app/mcp",
            tool_timeout=60,
        ),
        note="Connects securely in your browser with Linear OAuth.",
    ),
    McpPreset(
        name="github",
        display_name="GitHub",
        category="code",
        description="Repository, issue, and pull request workflows via GitHub's MCP server.",
        docs_url="https://github.com/github/github-mcp-server",
        transport="stdio",
        install_supported=True,
        brand_domain="github.com",
        brand_color="#24292F",
        requires="Docker and GitHub token",
        server=MCPServerConfig(
            type="stdio",
            command="docker",
            args=[
                "run",
                "-i",
                "--rm",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "ghcr.io/github/github-mcp-server",
            ],
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="github_token",
                label="GitHub token",
                target=("env", "GITHUB_PERSONAL_ACCESS_TOKEN"),
                env_var="GITHUB_PERSONAL_ACCESS_TOKEN",
                placeholder="ghp_...",
            ),
        ),
    ),
    McpPreset(
        name="supabase",
        display_name="Supabase",
        category="database",
        description="Inspect and manage Supabase projects through the Supabase MCP server.",
        docs_url="https://supabase.com/docs/guides/ai-tools/mcp",
        transport="stdio",
        install_supported=True,
        brand_domain="supabase.com",
        brand_color="#3ECF8E",
        requires="Node.js, npx, and Supabase access token",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@supabase/mcp-server-supabase@latest", "--read-only"],
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="supabase_access_token",
                label="Supabase access token",
                target=("env", "SUPABASE_ACCESS_TOKEN"),
                env_var="SUPABASE_ACCESS_TOKEN",
                placeholder="sbp_...",
            ),
        ),
        note="MVP config starts read-only by default.",
    ),
)


def _query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _query_value(query: QueryParams, key: str) -> str | None:
    raw = _query_first(query, key)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _preset_by_name(name: str) -> McpPreset:
    if not name or _MCP_PRESET_NAME_RE.match(name) is None:
        raise McpPresetError("invalid MCP preset name")
    for preset in MCP_PRESETS:
        if preset.name == name:
            return preset
    raise McpPresetError("unknown MCP preset", status=404)


def _preset_by_name_optional(name: str) -> McpPreset | None:
    try:
        return _preset_by_name(name)
    except McpPresetError:
        return None


def _known_preset_names() -> set[str]:
    return {preset.name for preset in MCP_PRESETS}


def _known_mcp_names(config_path: Path | None = None) -> set[str]:
    names = _known_preset_names()
    with suppress(Exception):
        names.update(load_config(config_path).tools.mcp_servers)
    return names


def _clip_ws_string(value: Any, limit: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]


def normalize_mcp_preset_mentions(
    raw: Any,
    *,
    config_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Sanitize structured MCP preset mentions sent by the WebUI."""
    if not isinstance(raw, list):
        return []
    known = _known_mcp_names(config_path)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item_value in cast(list[object], raw)[:8]:
        if not isinstance(item_value, dict):
            continue
        item = cast(dict[str, Any], item_value)
        name = _clip_ws_string(item.get("name"), 64)
        if not name or _MCP_PRESET_NAME_RE.match(name) is None:
            continue
        key = name.lower()
        if key in seen or key not in known:
            continue
        seen.add(key)
        row: dict[str, Any] = {"name": key}
        for field_name in _MCP_ATTACHMENT_KEYS[1:]:
            value = item.get(field_name)
            if isinstance(value, bool):
                row[field_name] = value
                continue
            limit = 512 if field_name == "logo_url" else 160
            text = _clip_ws_string(value, limit)
            if text:
                row[field_name] = text
        out.append(row)
    return out


def _clone_server(server: MCPServerConfig) -> MCPServerConfig:
    return MCPServerConfig.model_validate(server.model_dump(mode="json"))


def _with_managed_stdio_cwd(name: str, cfg: MCPServerConfig) -> MCPServerConfig:
    if cfg.command and (cfg.type in (None, "stdio")) and not cfg.cwd:
        cfg.cwd = str(ensure_dir(get_runtime_subdir("mcp") / name))
    return cfg


def _remove_managed_stdio_cwd(name: str, cfg: MCPServerConfig | None) -> bool:
    if cfg is None or not cfg.cwd:
        return False
    cwd = Path(cfg.cwd).expanduser().resolve(strict=False)
    managed = (get_runtime_subdir("mcp") / name).resolve(strict=False)
    if cwd != managed or not cwd.exists():
        return False
    if cwd.is_symlink() or cwd.is_file():
        cwd.unlink()
    else:
        shutil.rmtree(cwd)
    return True


def _url_with_param(url: str, key: str, value: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k != key]
    query.append((key, value))
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            parsed.fragment,
        )
    )


def _arg_value(args: list[str], flag: str) -> str | None:
    prefix = f"{flag}="
    for index, item in enumerate(args):
        if item == flag and index + 1 < len(args):
            return args[index + 1]
        if item.startswith(prefix):
            return item[len(prefix):]
    return None


def _with_arg_value(args: list[str], flag: str, value: str) -> list[str]:
    out: list[str] = []
    skip_next = False
    prefix = f"{flag}="
    for item in args:
        if skip_next:
            skip_next = False
            continue
        if item == flag:
            skip_next = True
            continue
        if item.startswith(prefix):
            continue
        out.append(item)
    out.extend([flag, value])
    return out


def _field_value_from_config(field: McpPresetField, cfg: MCPServerConfig | None) -> str | None:
    if cfg is None:
        return None
    target_kind, target_name = field.target
    if target_kind == "env":
        value = cfg.env.get(target_name)
        return value if value else None
    if target_kind == "header":
        value = cfg.headers.get(target_name)
        return value if value else None
    if target_kind == "arg":
        return _arg_value(list(cfg.args), target_name)
    if target_kind == "url_param" and cfg.url:
        parsed = urllib.parse.urlsplit(cfg.url)
        values = urllib.parse.parse_qs(parsed.query).get(target_name)
        if values:
            return values[0]
    return None


def _field_configured(field: McpPresetField, cfg: MCPServerConfig | None) -> bool:
    value = _field_value_from_config(field, cfg)
    if value:
        return True
    return bool(field.env_var and os.environ.get(field.env_var))


def _field_payload(field: McpPresetField, cfg: MCPServerConfig | None) -> dict[str, Any]:
    return {
        "name": field.name,
        "label": field.label,
        "secret": field.secret,
        "required": field.required,
        "configured": _field_configured(field, cfg),
        "placeholder": field.placeholder,
        "env_var": field.env_var,
    }


def _resolve_field_value(
    field: McpPresetField,
    query: QueryParams,
    existing: MCPServerConfig | None,
) -> str | None:
    provided = _query_value(query, field.name)
    if provided:
        return provided
    current = _field_value_from_config(field, existing)
    if current:
        return current
    if field.env_var and os.environ.get(field.env_var):
        return f"${{{field.env_var}}}"
    return None


def _materialize_server(
    preset: McpPreset,
    query: QueryParams,
    existing: MCPServerConfig | None,
) -> MCPServerConfig:
    if preset.server is None or not preset.install_supported:
        raise McpPresetError(f"{preset.display_name} is not supported yet", status=409)

    cfg = _clone_server(preset.server)
    for field_spec in preset.fields:
        value = _resolve_field_value(field_spec, query, existing)
        if field_spec.required and not value:
            raise McpPresetError(f"missing {field_spec.label}")
        if not value:
            continue
        target_kind, target_name = field_spec.target
        if target_kind == "env":
            cfg.env[target_name] = value
        elif target_kind == "header":
            cfg.headers[target_name] = value
        elif target_kind == "arg":
            cfg.args = _with_arg_value(list(cfg.args), target_name, value)
        elif target_kind == "url_param":
            cfg.url = _url_with_param(cfg.url, target_name, value)
    return _with_managed_stdio_cwd(preset.name, cfg)


def _command_available(command: str) -> bool:
    if not command:
        return False
    if shutil.which(command):
        return True
    path = Path(command).expanduser()
    return path.exists() and path.is_file()


def _config_available(cfg: MCPServerConfig | None) -> bool:
    if cfg is None:
        return False
    if cfg.command:
        return _command_available(cfg.command)
    if cfg.url:
        return True
    return False


def _status_for(preset: McpPreset, cfg: MCPServerConfig | None) -> str:
    if cfg is None:
        return "not_installed" if preset.install_supported else "coming_soon"
    if any(field.required and not _field_configured(field, cfg) for field in preset.fields):
        return "missing_credentials"
    if cfg.auth == "oauth" and not mcp_oauth_has_credentials(preset.name, cfg.url):
        return "authorization_required"
    if cfg.command and not _command_available(cfg.command):
        return "missing_dependency"
    return "configured"


def _connection_summary(cfg: MCPServerConfig | None) -> str:
    if cfg is None:
        return ""
    if cfg.command:
        return " ".join([cfg.command, *cfg.args[:2]]).strip()
    if cfg.url:
        parsed = urllib.parse.urlsplit(cfg.url)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return ""


def _tool_allowlist(cfg: MCPServerConfig | None) -> list[str]:
    if cfg is None:
        return ["*"]
    return list(cfg.enabled_tools)


def _managed_mcp_path(name: str, cfg: MCPServerConfig | None) -> list[str]:
    if cfg is None or not cfg.command:
        return []
    return [f"runtime:mcp/{name}"]


def _preset_manifest(preset: McpPreset, *, logo_url: str) -> dict[str, Any]:
    server = preset.server
    managed_paths = _managed_mcp_path(preset.name, server)
    field_specs = [
        compact_dict({
            "name": field.name,
            "target": field.target[0],
            "required": field.required,
            "secret": field.secret,
            "env_var": field.env_var,
        })
        for field in preset.fields
    ]
    capabilities = [
        compact_dict({
            "type": "mcp",
            "transport": preset.transport,
            "auth": server.auth if server and server.auth else None,
            "command": server.command if server and server.command else None,
            "args": list(server.args) if server and server.command else None,
            "url": _connection_summary(server) if server and server.url else None,
            "fields": field_specs,
        })
    ]
    return app_manifest(
        app_id=preset.name,
        display_name=preset.display_name,
        description=preset.description,
        category=preset.category,
        source="mcp-preset",
        docs_url=preset.docs_url,
        logo_url=logo_url,
        brand_color=preset.brand_color,
        capabilities=capabilities,
        install=compact_dict({
            "supported": preset.install_supported,
            "strategy": "config",
            "managed_paths": managed_paths,
            "verification": ["config_present", "dependency_available"],
        }),
        remove=compact_dict({
            "supported": True,
            "strategy": "config",
            "managed_paths": managed_paths,
            "verification": ["config_absent", "managed_paths_absent"] if managed_paths else ["config_absent"],
        }),
        trust={
            "registry": "mcp-presets",
            "level": "builtin",
            "review_status": "builtin_preset",
        },
    )


def _custom_manifest(name: str, cfg: MCPServerConfig) -> dict[str, Any]:
    transport = cfg.type or ("stdio" if cfg.command else "streamableHttp")
    managed_paths: list[str] = []
    return app_manifest(
        app_id=name,
        display_name=name,
        description="Custom MCP server from nanobot config.",
        category="custom",
        source="mcp-custom",
        brand_color="#64748B",
        capabilities=[
            compact_dict({
                "type": "mcp",
                "transport": transport,
                "auth": cfg.auth,
                "command": cfg.command or None,
                "url": _connection_summary(cfg) if cfg.url else None,
            })
        ],
        install=compact_dict({
            "supported": True,
            "strategy": "config",
            "managed_paths": managed_paths,
            "verification": ["config_present", "dependency_available"],
        }),
        remove=compact_dict({
            "supported": True,
            "strategy": "config",
            "managed_paths": managed_paths,
            "verification": ["config_absent", "managed_paths_absent"] if managed_paths else ["config_absent"],
        }),
        trust={
            "registry": "user-config",
            "level": "user",
            "review_status": "user_managed",
        },
    )


def _preset_payload(preset: McpPreset, configured_servers: dict[str, MCPServerConfig]) -> dict[str, Any]:
    cfg = configured_servers.get(preset.name)
    status = _status_for(preset, cfg)
    configured = cfg is not None and status not in {"missing_credentials", "authorization_required"}
    logo_url = _favicon_url(preset.brand_domain)
    return {
        "name": preset.name,
        "display_name": preset.display_name,
        "category": preset.category,
        "description": preset.description,
        "docs_url": preset.docs_url,
        "transport": preset.transport,
        "auth": (cfg.auth if cfg is not None else (preset.server.auth if preset.server else None)),
        "requires": preset.requires,
        "note": preset.note,
        "install_supported": preset.install_supported,
        "installed": cfg is not None,
        "configured": configured,
        "available": configured and _config_available(cfg),
        "status": status,
        "logo_url": logo_url,
        "brand_color": preset.brand_color,
        "required_fields": [_field_payload(field, cfg) for field in preset.fields],
        "connection_summary": _connection_summary(cfg),
        "enabled_tools": _tool_allowlist(cfg),
        "source": "preset",
        "manifest": _preset_manifest(preset, logo_url=logo_url),
    }


def _custom_payload(
    name: str,
    cfg: MCPServerConfig,
    *,
    tool_names: list[str] | None = None,
) -> dict[str, Any]:
    transport = cfg.type
    if not transport:
        transport = "stdio" if cfg.command else ("sse" if cfg.url.rstrip("/").endswith("/sse") else "streamableHttp")
    if cfg.auth == "oauth" and not mcp_oauth_has_credentials(name, cfg.url):
        status = "authorization_required"
    else:
        status = "missing_dependency" if cfg.command and not _command_available(cfg.command) else "configured"
    configured = status != "authorization_required"
    return {
        "name": name,
        "display_name": name,
        "category": "custom",
        "description": "Custom MCP server from nanobot config.",
        "docs_url": "",
        "transport": transport,
        "auth": cfg.auth,
        "requires": "",
        "note": "",
        "install_supported": True,
        "installed": True,
        "configured": configured,
        "available": configured and _config_available(cfg),
        "status": status,
        "logo_url": None,
        "brand_color": "#64748B",
        "required_fields": [],
        "connection_summary": _connection_summary(cfg),
        "enabled_tools": _tool_allowlist(cfg),
        "tool_names": tool_names or [],
        "source": "custom",
        "manifest": _custom_manifest(name, cfg),
    }


def _agent_plugin_payload(plugin: AgentPlugin) -> dict[str, Any]:
    return {
        "name": f"plugin-{plugin.name}",
        "display_name": plugin.display_name,
        "category": plugin.category,
        "description": plugin.description or "Agent Plugin",
        "docs_url": plugin.repository,
        "transport": "stdio",
        "requires": ", ".join(plugin.permissions),
        "note": "",
        "install_supported": False,
        "installed": True,
        "configured": True,
        "enabled": plugin.enabled,
        "available": plugin.enabled,
        "status": "enabled" if plugin.enabled else "disabled",
        "logo_url": plugin.logo,
        "brand_color": plugin.accent_color,
        "required_fields": [],
        "connection_summary": ", ".join(plugin.mcp_servers),
        "source": "agent-plugin",
    }


def mcp_presets_payload(
    *,
    last_action: dict[str, Any] | None = None,
    tool_preview: Mapping[str, list[str]] | None = None,
    runtime_status: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = load_config(config_path) if config_path is not None else load_config()
    known = _known_preset_names()
    preset_rows: list[dict[str, Any]] = [
        _preset_payload(preset, config.tools.mcp_servers)
        | ({"tool_names": tool_preview.get(preset.name, [])} if tool_preview and preset.name in tool_preview else {})
        for preset in MCP_PRESETS
    ]
    driver = CuaDriver(config_path or get_config_path())
    for row in preset_rows:
        if row["name"] == "cua-driver":
            row["driver_setup"] = driver.info(config.tools.mcp_servers.get("cua-driver"))
            row["logo_url"] = None
            row["manifest"]["install"] = {
                "supported": driver.release is not None, "strategy": "verified-driver",
                "confirmation_required": True, "verification": ["sha256", "platform_package"],
            }
            row["manifest"]["remove"] = {
                "supported": True, "strategy": "disable", "verification": ["config_absent"],
                "note": "Disables tools; retains the downloaded package and OS permissions.",
            }
    custom_rows = [
        _custom_payload(name, cfg, tool_names=(tool_preview or {}).get(name))
        for name, cfg in sorted(config.tools.mcp_servers.items())
        if name not in known
    ]
    existing_names = {str(row["name"]) for row in (*preset_rows, *custom_rows)}
    plugin_rows = [
        _agent_plugin_payload(plugin)
        for plugin in discover_agent_plugins(config.workspace_path)
        if f"plugin-{plugin.name}" not in existing_names
    ]
    payload: dict[str, Any] = {
        "capabilities": [CUA_CAPABILITY, CUA_SETUP_CAPABILITY, CUA_PERMISSIONS_CAPABILITY, CUA_RECONNECT_CAPABILITY, CUA_UNINSTALL_CAPABILITY, CUA_NATIVE_CAPABILITY, CUA_UNINSTALL_RESET_CAPABILITY],
        "presets": [*preset_rows, *custom_rows, *plugin_rows],
        "installed_count": len(config.tools.mcp_servers)
        + sum(int(row["enabled"]) for row in plugin_rows),
    }
    if last_action is not None:
        payload["last_action"] = last_action
    return attach_mcp_runtime_status(payload, runtime_status)


def attach_mcp_runtime_status(
    payload: dict[str, Any],
    runtime_status: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Project safe, connection-attempt state onto eligible installed MCP rows."""
    if runtime_status is None:
        return payload
    projected = dict(payload)
    raw_rows: object = payload.get("presets", [])
    preset_rows = cast(list[object], raw_rows) if isinstance(raw_rows, list) else []
    rows: list[Any] = []
    for raw_row in preset_rows:
        if not isinstance(raw_row, dict):
            rows.append(raw_row)
            continue
        row = dict(cast(dict[str, Any], raw_row))
        name = row.get("name")
        status = runtime_status.get(name) if isinstance(name, str) else None
        oauth_authorization_failed = (
            status == "failed"
            and row.get("auth") == "oauth"
            and row.get("status") == "authorization_required"
        )
        if (
            status in _MCP_RUNTIME_STATUSES
            and row.get("installed") is True
            and (row.get("configured") is True or oauth_authorization_failed)
        ):
            row["runtime_status"] = status
        else:
            row.pop("runtime_status", None)
        rows.append(row)
    projected["presets"] = rows
    return projected


def _display_name_for(name: str, preset: McpPreset | None = None) -> str:
    return preset.display_name if preset is not None else name


def _action_message(action: str, preset: McpPreset, *, ok: bool = True) -> dict[str, Any]:
    verb = {
        "enable": "Enabled",
        "remove": "Removed",
        "test": "Checked",
    }.get(action, "Updated")
    payload: dict[str, Any] = {
        "ok": ok,
        "message": f"{verb} MCP preset for {preset.display_name}.",
    }
    if action == "enable":
        payload["installed"] = True
        payload["verification"] = ["config_present"]
    elif action == "remove":
        payload["removed"] = True
        payload["verification"] = ["config_absent"]
    return payload


def _server_action_message(action: str, name: str, *, ok: bool = True) -> dict[str, Any]:
    verb = {
        "custom": "Saved",
        "import": "Imported",
        "import-cursor": "Imported",
        "tools": "Updated tools for",
        "remove": "Removed",
        "reconnect": "Retried connection for",
    }.get(action, "Updated")
    payload: dict[str, Any] = {
        "ok": ok,
        "message": f"{verb} MCP server {name}.",
    }
    if action in {"custom", "import", "import-cursor"}:
        payload["installed"] = True
        payload["verification"] = ["config_present"]
    elif action == "remove":
        payload["removed"] = True
        payload["verification"] = ["config_absent"]
    return payload


def mcp_reconnect_action(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a configured server before asking the live runtime to retry it."""
    name = _validated_server_name((_query_first(query, "name") or "").strip())
    config = load_config(config_path) if config_path is not None else load_config()
    if name not in config.tools.mcp_servers:
        raise McpPresetError("unknown MCP server", status=404)
    payload = mcp_presets_payload(
        last_action=_server_action_message("reconnect", name),
        config_path=config_path,
    )
    payload["requires_restart"] = True
    return payload


def _scrub_test_error(text: str) -> str:
    scrubbed = _SECRET_QUERY_RE.sub(r"\1<redacted>", text.strip())
    scrubbed = _SECRET_ASSIGNMENT_RE.sub(r"\1<redacted>", scrubbed)
    return scrubbed[:400] if scrubbed else "Connection failed."


def _checked_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _test_timeout(cfg: MCPServerConfig) -> int:
    raw = cfg.tool_timeout or _DEFAULT_TEST_TIMEOUT
    return max(5, min(int(raw), _DEFAULT_TEST_TIMEOUT))


async def _close_mcp_stacks(stacks: Mapping[str, Any]) -> None:
    for stack in stacks.values():
        with suppress(Exception):
            await stack.aclose()


async def mcp_presets_test_action(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Connect to an enabled MCP preset and report its complete tool surface."""
    from nanobot.agent.tools.mcp import connect_mcp_servers

    name = (_query_first(query, "name") or "").strip()
    if not name:
        raise McpPresetError("missing MCP preset name")
    if _MCP_PRESET_NAME_RE.match(name) is None:
        raise McpPresetError("invalid MCP server name")
    preset = _preset_by_name_optional(name)
    display_name = _display_name_for(name, preset)

    try:
        config = resolve_config_env_vars(
            load_config(config_path) if config_path is not None else load_config(),
            config_path=config_path,
        )
    except ValueError as exc:
        return mcp_presets_payload(
            last_action={
                "ok": False,
                "message": _scrub_test_error(str(exc)),
                "error": _scrub_test_error(str(exc)),
                "tool_count": 0,
                "tool_names": [],
                "checked_at": _checked_at(),
            },
            config_path=config_path,
        )

    cfg = config.tools.mcp_servers.get(name)
    if cfg is None:
        raise McpPresetError(f"{display_name} is not enabled", status=404)

    status = _status_for(preset, cfg) if preset is not None else (
        "missing_dependency" if cfg.command and not _command_available(cfg.command) else "configured"
    )
    if status == "missing_credentials":
        last_action: dict[str, Any] = {
            "ok": False,
            "message": f"{display_name} is missing required credentials.",
            "error": "missing credentials",
            "tool_count": 0,
            "tool_names": [],
            "checked_at": _checked_at(),
        }
        return mcp_presets_payload(last_action=last_action, config_path=config_path)

    if cfg.command and not _command_available(cfg.command):
        last_action = {
            "ok": False,
            "message": f"{display_name} requires '{cfg.command}' on PATH.",
            "error": "missing dependency",
            "tool_count": 0,
            "tool_names": [],
            "checked_at": _checked_at(),
        }
        return mcp_presets_payload(last_action=last_action, config_path=config_path)

    registry = ToolRegistry()
    stacks: dict[str, Any] = {}
    inspection_cfg = cfg.model_copy(update={"enabled_tools": ["*"]})
    try:
        stacks = await asyncio.wait_for(
            connect_mcp_servers({name: inspection_cfg}, registry),
            timeout=_test_timeout(cfg),
        )
        tool_prefix = f"mcp_{name}_"
        tool_names = sorted(
            tool_name
            for tool_name in registry.tool_names
            if tool_name.startswith(tool_prefix)
        )
        ok = name in stacks
        if ok:
            last_action = {
                "ok": True,
                "message": (
                    f"{display_name} connected with {len(tool_names)} tools."
                    if tool_names
                    else f"{display_name} connected, but reported no tools."
                ),
                "tool_count": len(tool_names),
                "tool_names": tool_names,
                "checked_at": _checked_at(),
            }
        else:
            last_action = {
                "ok": False,
                "message": f"{display_name} did not complete an MCP handshake.",
                "error": "MCP handshake failed",
                "tool_count": 0,
                "tool_names": [],
                "checked_at": _checked_at(),
            }
    except asyncio.TimeoutError:
        last_action = {
            "ok": False,
            "message": f"{display_name} test timed out.",
            "error": "timeout",
            "tool_count": 0,
            "tool_names": [],
            "checked_at": _checked_at(),
        }
    except Exception as exc:
        error = _scrub_test_error(str(exc))
        last_action = {
            "ok": False,
            "message": f"{display_name} could not connect.",
            "error": error,
            "tool_count": 0,
            "tool_names": [],
            "checked_at": _checked_at(),
        }
    finally:
        await _close_mcp_stacks(stacks)

    tool_names = last_action.get("tool_names", [])
    preview = {name: tool_names} if tool_names else None
    return mcp_presets_payload(
        last_action=last_action,
        tool_preview=preview,
        config_path=config_path,
    )


def _parse_json_value(raw: str | None, *, fallback: Any) -> Any:
    if raw is None or not raw.strip():
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise McpPresetError(f"invalid JSON: {exc.msg}") from exc


def _parse_string_list(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return []
    parsed = _parse_json_value(raw, fallback=None)
    if isinstance(parsed, list):
        items = cast(list[object], parsed)
        if all(isinstance(item, str) for item in items):
            return [item for item in cast(list[str], items) if item.strip()]
    if isinstance(parsed, str):
        return shlex.split(parsed)
    raise McpPresetError("expected a JSON string array")


def _parse_string_map(raw: str | None) -> dict[str, str]:
    parsed = _parse_json_value(raw, fallback={})
    if not isinstance(parsed, dict):
        raise McpPresetError("expected a JSON object")
    out: dict[str, str] = {}
    for key, value in cast(dict[object, object], parsed).items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise McpPresetError("JSON object values must be strings")
        if key.strip():
            out[key.strip()] = value
    return out


def _parse_enabled_tools(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return ["*"]
    values = _parse_string_list(raw)
    if "*" in values:
        return ["*"]
    return values


def _normalize_transport(value: str | None, *, command: str = "", url: str = "") -> Literal["stdio", "sse", "streamableHttp"]:
    raw = (value or "").strip()
    if not raw:
        if command:
            return "stdio"
        if url.rstrip("/").endswith("/sse"):
            return "sse"
        return "streamableHttp"
    aliases = {
        "stdio": "stdio",
        "sse": "sse",
        "streamableHttp": "streamableHttp",
        "streamable-http": "streamableHttp",
        "streamable_http": "streamableHttp",
        "http": "streamableHttp",
    }
    normalized = aliases.get(raw)
    if normalized is None:
        raise McpPresetError("unsupported MCP transport")
    return normalized  # type: ignore[return-value]


def _normalize_auth(
    value: object,
    *,
    transport: Literal["stdio", "sse", "streamableHttp"],
    url: str,
    headers: Mapping[str, str],
) -> Literal["oauth"] | None:
    raw = str(value or "").strip().lower()
    if not raw and url and not headers:
        normalized_url = url.rstrip("/")
        if any(
            preset.server is not None
            and preset.server.auth == "oauth"
            and preset.server.url.rstrip("/") == normalized_url
            for preset in MCP_PRESETS
        ):
            raw = "oauth"
    if not raw:
        return None
    if raw != "oauth":
        raise McpPresetError("unsupported MCP auth type")
    if transport == "stdio":
        raise McpPresetError("MCP OAuth requires a remote HTTP transport")
    return "oauth"


def _validated_server_name(name: str) -> str:
    if not name or _MCP_PRESET_NAME_RE.match(name) is None:
        raise McpPresetError("invalid MCP server name")
    return name.strip().lower()


def _custom_server_from_query(query: QueryParams) -> tuple[str, MCPServerConfig]:
    name = _validated_server_name((_query_first(query, "name") or "").strip())
    command = (_query_first(query, "command") or "").strip()
    url = (_query_first(query, "url") or "").strip()
    transport = _normalize_transport(_query_first(query, "transport"), command=command, url=url)
    if transport == "stdio" and not command:
        raise McpPresetError("stdio MCP servers require a command")
    if transport in {"sse", "streamableHttp"} and not url:
        raise McpPresetError("remote MCP servers require a URL")
    headers = _parse_string_map(_query_first(query, "headers"))
    auth = _normalize_auth(
        _query_first(query, "auth"),
        transport=transport,
        url=url,
        headers=headers,
    )
    raw_timeout = (_query_first(query, "tool_timeout") or "").strip()
    tool_timeout = _DEFAULT_CUSTOM_TIMEOUT
    if raw_timeout:
        try:
            tool_timeout = max(5, min(int(raw_timeout), 600))
        except ValueError as exc:
            raise McpPresetError("tool_timeout must be an integer") from exc
    cfg = MCPServerConfig(
        type=transport,
        auth=auth,
        command=command if transport == "stdio" else "",
        args=_parse_string_list(_query_first(query, "args")),
        env=_parse_string_map(_query_first(query, "env")),
        cwd=(_query_first(query, "cwd") or "").strip() if transport == "stdio" else "",
        url=url if transport in {"sse", "streamableHttp"} else "",
        headers=headers,
        tool_timeout=tool_timeout,
        enabled_tools=_parse_enabled_tools(_query_first(query, "enabled_tools")),
    )
    return name, cfg


def _mcp_server_config(name: str, raw: Any) -> tuple[str, MCPServerConfig]:
    server_name = _validated_server_name(name)
    if not isinstance(raw, Mapping):
        raise McpPresetError(f"MCP server '{server_name}' must be an object")
    server = cast(Mapping[str, Any], raw)
    command = str(server.get("command") or "").strip()
    url = str(server.get("url") or "").strip()
    transport_value = str(server.get("type", server.get("transport", "")) or "")
    transport = _normalize_transport(transport_value, command=command, url=url)
    if transport == "stdio" and not command:
        raise McpPresetError(f"MCP server '{server_name}' stdio transport requires a command")
    if transport in {"sse", "streamableHttp"} and not url:
        raise McpPresetError(f"MCP server '{server_name}' remote transport requires a URL")
    args_value: object = server.get("args") or []
    env_value: object = server.get("env") or {}
    headers_value: object = server.get("headers") or {}
    cwd = str(server.get("cwd") or "").strip()
    enabled_tools_value: object = server.get("enabledTools", server.get("enabled_tools", ["*"]))
    image_output = server.get("imageOutput", server.get("image_output", "artifact"))
    retry_tool_calls = server.get("retryToolCalls", server.get("retry_tool_calls", True))
    if image_output not in ("artifact", "inline"):
        raise McpPresetError("imageOutput must be artifact or inline")
    if not isinstance(retry_tool_calls, bool):
        raise McpPresetError("retryToolCalls must be a boolean")
    tool_timeout: object = server.get("toolTimeout", server.get("tool_timeout", _DEFAULT_CUSTOM_TIMEOUT))
    try:
        timeout_int = max(5, min(int(cast(Any, tool_timeout)), 600))
    except (TypeError, ValueError):
        timeout_int = _DEFAULT_CUSTOM_TIMEOUT
    if not isinstance(args_value, list):
        raise McpPresetError(f"MCP server '{server_name}' args must be a string array")
    args = cast(list[object], args_value)
    if not all(isinstance(item, str) for item in args):
        raise McpPresetError(f"MCP server '{server_name}' args must be a string array")
    if not isinstance(env_value, dict):
        raise McpPresetError(f"MCP server '{server_name}' env must be a string object")
    env = cast(dict[object, object], env_value)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise McpPresetError(f"MCP server '{server_name}' env must be a string object")
    if not isinstance(headers_value, dict):
        raise McpPresetError(f"MCP server '{server_name}' headers must be a string object")
    headers = cast(dict[object, object], headers_value)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
        raise McpPresetError(f"MCP server '{server_name}' headers must be a string object")
    typed_headers = cast(dict[str, str], headers)
    auth = _normalize_auth(
        server.get("auth"),
        transport=transport,
        url=url,
        headers=typed_headers,
    )
    if not isinstance(enabled_tools_value, list):
        enabled_tools_value = ["*"]
    else:
        enabled_tools = cast(list[object], enabled_tools_value)
        if not all(isinstance(item, str) for item in enabled_tools):
            enabled_tools_value = ["*"]
    return server_name, MCPServerConfig(
        type=transport,
        auth=auth,
        command=command if transport == "stdio" else "",
        args=cast(list[str], args),
        env=cast(dict[str, str], env),
        cwd=cwd if transport == "stdio" else "",
        url=url if transport in {"sse", "streamableHttp"} else "",
        headers=typed_headers,
        tool_timeout=timeout_int,
        image_output=image_output,
        retry_tool_calls=retry_tool_calls,
        enabled_tools=cast(list[str], enabled_tools_value),
    )


def _import_mcp_servers(raw_json: str | None) -> dict[str, MCPServerConfig]:
    parsed = _parse_json_value(raw_json, fallback=None)
    if not isinstance(parsed, Mapping):
        raise McpPresetError("MCP config must be a JSON object")
    parsed_mapping = cast(Mapping[str, Any], parsed)
    servers: object = parsed_mapping.get("mcpServers", parsed_mapping)
    if not isinstance(servers, Mapping):
        raise McpPresetError("MCP config must contain mcpServers")
    out: dict[str, MCPServerConfig] = {}
    for name, raw_server in cast(Mapping[object, object], servers).items():
        if not isinstance(name, str):
            raise McpPresetError("MCP server names must be strings")
        server_name, cfg = _mcp_server_config(name, raw_server)
        out[server_name] = cfg
    if not out:
        raise McpPresetError("MCP config contains no servers")
    return out


def _oauth_credentials_replaced(
    previous: MCPServerConfig | None,
    replacement: MCPServerConfig,
) -> bool:
    if previous is None or previous.auth != "oauth":
        return False
    return replacement.auth != "oauth" or replacement.url != previous.url


def custom_mcp_action(
    action: str,
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config = load_config(config_path) if config_path is not None else load_config()
    if action == "custom":
        name, cfg = _custom_server_from_query(query)
        previous = config.tools.mcp_servers.get(name)
        if previous is not None:
            # The connection form does not expose these advanced JSON settings.
            cfg.image_output = previous.image_output
            cfg.retry_tool_calls = previous.retry_tool_calls
        delete_credentials = _oauth_credentials_replaced(previous, cfg)
        config.tools.mcp_servers[name] = cfg
        save_config(config, config_path)
        if delete_credentials:
            delete_mcp_oauth_credentials(name)
        payload = mcp_presets_payload(
            last_action=_server_action_message(action, name),
            config_path=config_path,
        )
        payload["requires_restart"] = True
        return payload

    if action in {"import", "import-cursor"}:
        servers = _import_mcp_servers(_query_first(query, "config"))
        delete_credentials = [
            name
            for name, cfg in servers.items()
            if _oauth_credentials_replaced(config.tools.mcp_servers.get(name), cfg)
        ]
        config.tools.mcp_servers.update(servers)
        save_config(config, config_path)
        for name in delete_credentials:
            delete_mcp_oauth_credentials(name)
        payload = mcp_presets_payload(
            last_action={
                "ok": True,
                "message": f"Imported {len(servers)} MCP server(s).",
            },
            config_path=config_path,
        )
        payload["requires_restart"] = True
        return payload

    if action == "tools":
        name = _validated_server_name((_query_first(query, "name") or "").strip())
        cfg = config.tools.mcp_servers.get(name)
        if cfg is None:
            raise McpPresetError("unknown MCP server", status=404)
        cfg.enabled_tools = _parse_enabled_tools(_query_first(query, "enabled_tools"))
        config.tools.mcp_servers[name] = cfg
        save_config(config, config_path)
        payload = mcp_presets_payload(
            last_action=_server_action_message(action, name),
            config_path=config_path,
        )
        payload["requires_restart"] = True
        return payload

    raise McpPresetError(f"unknown MCP action '{action}'", status=404)


def ensure_mcp_oauth_server(
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> tuple[str, MCPServerConfig]:
    """Materialize an OAuth preset on first click and return its saved config."""
    name = _validated_server_name((_query_first(query, "name") or "").strip())
    config = load_config(config_path) if config_path is not None else load_config()
    cfg = config.tools.mcp_servers.get(name)
    if cfg is None:
        preset = _preset_by_name(name)
        if preset.server is None or preset.server.auth != "oauth":
            raise McpPresetError("MCP server does not support browser authorization", status=409)
        cfg = _materialize_server(preset, query, None)
        config.tools.mcp_servers[name] = cfg
        save_config(config, config_path)
    if cfg.auth != "oauth" or cfg.type not in {"sse", "streamableHttp"} or not cfg.url:
        raise McpPresetError("MCP server is not configured for OAuth", status=409)
    return name, cfg


def mcp_presets_action(
    action: str,
    query: QueryParams,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    name = (_query_first(query, "name") or "").strip()
    if not name:
        raise McpPresetError("missing MCP preset name")
    if name == "cua-driver" and action != "remove":
        raise McpPresetError("Cua Driver requires its explicit installation and desktop-access setup flow.")
    preset = _preset_by_name_optional(name)

    config = load_config(config_path) if config_path is not None else load_config()
    existing = config.tools.mcp_servers.get(name)

    if action == "enable":
        if preset is None:
            raise McpPresetError("unknown MCP preset", status=404)
        config.tools.mcp_servers[preset.name] = _materialize_server(preset, query, existing)
        save_config(config, config_path)
        payload = mcp_presets_payload(
            last_action=_action_message(action, preset),
            config_path=config_path,
        )
        payload["requires_restart"] = True
        return payload

    if action == "remove":
        if preset is None and name not in config.tools.mcp_servers:
            raise McpPresetError("unknown MCP server", status=404)
        removed_runtime_files = False
        cleanup_error = ""
        if name in config.tools.mcp_servers:
            existing_cfg = config.tools.mcp_servers[name]
            try:
                removed_runtime_files = _remove_managed_stdio_cwd(name, existing_cfg)
            except OSError as exc:
                cleanup_error = str(exc)
            del config.tools.mcp_servers[name]
            save_config(config, config_path)
            delete_mcp_oauth_credentials(name)
        last_action = (
            _action_message(action, preset)
            if preset is not None
            else _server_action_message(action, name)
        )
        if removed_runtime_files:
            last_action["message"] = f"{last_action['message']} Removed managed runtime files."
            last_action["managed_paths_removed"] = [f"runtime:mcp/{name}"]
            last_action["verification"] = ["config_absent", "managed_paths_absent"]
        if cleanup_error:
            last_action["ok"] = False
            last_action["message"] = (
                f"{last_action['message']} Could not remove managed runtime files: {cleanup_error}"
            )
            last_action["verification_failed"] = ["managed_paths_absent"]
        payload = mcp_presets_payload(
            last_action=last_action,
            config_path=config_path,
        )
        payload["requires_restart"] = True
        return payload

    if action == "test":
        raise McpPresetError("MCP preset test must run through the async test action", status=500)

    raise McpPresetError(f"unknown MCP preset action '{action}'", status=404)


def attach_mcp_hot_reload_result(
    payload: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Merge an agent MCP reload acknowledgement into a WebUI settings payload."""
    payload = dict(payload)
    payload["hot_reload"] = result
    payload["requires_restart"] = bool(result.get("requires_restart"))
    last_action = dict(payload.get("last_action") or {})
    base_message = str(last_action.get("message") or "").strip()
    reload_message = str(result.get("message") or "").strip()
    if reload_message:
        last_action["message"] = (
            f"{base_message} {reload_message}" if base_message else reload_message
        )
    if "ok" not in last_action:
        last_action["ok"] = bool(result.get("ok", False))
    payload["last_action"] = last_action
    return payload


async def mcp_presets_settings_action(
    action: str | None,
    query: QueryParams,
    *,
    reload_mcp: MCPReload | None = None,
    mcp_runtime_status: McpRuntimeStatus | None = None,
    config: WebUISettingsConfig | None = None,
) -> dict[str, Any]:
    """Run a WebUI MCP preset action and hot-reload the agent when config changes."""
    config_path = config.path if config is not None else None
    if action is None:
        return mcp_presets_payload(
            runtime_status=mcp_runtime_status() if mcp_runtime_status is not None else None,
            config_path=config_path,
        )
    name = (_query_first(query, "name") or "").strip()
    if name == "cua-driver":
        saved_config = load_config(config_path)
        saved_driver = saved_config.tools.mcp_servers.get(name)
        managed_driver = saved_driver is None or CuaDriver(config_path or get_config_path()).owns(saved_driver)
        if managed_driver or action in {"enable", "install", "disable", "setup", "uninstall"}:
            return await _cua_driver_action(action, query, config=config, reload_mcp=reload_mcp,
                                            mcp_runtime_status=mcp_runtime_status)
    if action == "setup":
        raise McpPresetError("Native setup is only supported for managed Cua Driver.", 400)
    if name.startswith("plugin-"):
        plugin_config = load_config(config_path) if config_path is not None else load_config()
        plugin_name = name.removeprefix("plugin-")
        plugins = discover_agent_plugins(plugin_config.workspace_path)
        plugin = next((item for item in plugins if item.name == plugin_name), None)
        if name not in plugin_config.tools.mcp_servers and plugin is not None:
            if action not in {"enable", "disable"}:
                raise McpPresetError("Agent Plugins support enable and disable actions only")
            await asyncio.to_thread(
                set_agent_plugin_enabled,
                plugin_config.workspace_path,
                plugin_name,
                action == "enable",
            )
            verb = "enabled" if action == "enable" else "disabled"
            payload = mcp_presets_payload(
                last_action={"ok": True, "message": f"{plugin.display_name} {verb}."},
                config_path=config_path,
            )
            if reload_mcp is not None:
                payload = attach_mcp_hot_reload_result(payload, await reload_mcp())
            return payload
    if action == "test":
        payload = await mcp_presets_test_action(query, config_path=config_path)
        return attach_mcp_runtime_status(
            payload,
            mcp_runtime_status() if mcp_runtime_status is not None else None,
        )
    if action == "reconnect":
        payload = await asyncio.to_thread(
            mcp_reconnect_action,
            query,
            config_path=config_path,
        )
    elif config is not None:
        operation = custom_mcp_action if action in _CUSTOM_ACTIONS else mcp_presets_action
        payload = await asyncio.to_thread(
            config.run_serialized,
            lambda path: operation(action, query, config_path=path),
        )
    elif action in _CUSTOM_ACTIONS:
        payload = await asyncio.to_thread(custom_mcp_action, action, query)
    else:
        payload = await asyncio.to_thread(mcp_presets_action, action, query)
    if reload_mcp is not None:
        payload = attach_mcp_hot_reload_result(payload, await reload_mcp())
    return attach_mcp_runtime_status(
        payload,
        mcp_runtime_status() if mcp_runtime_status is not None else None,
    )


async def _cua_driver_action(
    action: str, query: QueryParams, *, config: WebUISettingsConfig | None,
    reload_mcp: MCPReload | None, mcp_runtime_status: McpRuntimeStatus | None,
) -> dict[str, Any]:
    """Serialize settings operations across tabs and gateway processes."""
    from filelock import FileLock, Timeout

    # A read-only permission probe must never delay disabling desktop access.
    # Its completion already rechecks current configuration before reloading.
    if action == "test":
        return await _cua_driver_action_locked(action, query, config=config,
            reload_mcp=reload_mcp, mcp_runtime_status=mcp_runtime_status)
    driver = CuaDriver(config.path if config is not None else get_config_path())
    driver.root.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(driver.root / "action.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise McpPresetError("Computer Use setup is already in progress. Wait for it to finish.", 409) from exc
    try:
        return await _cua_driver_action_locked(action, query, config=config,
            reload_mcp=reload_mcp, mcp_runtime_status=mcp_runtime_status)
    finally:
        lock.release()


async def _cua_driver_action_locked(
    action: str, query: QueryParams, *, config: WebUISettingsConfig | None,
    reload_mcp: MCPReload | None, mcp_runtime_status: McpRuntimeStatus | None,
) -> dict[str, Any]:
    """Own installer consent and configuration; do not expose native setup to the agent."""
    from nanobot.webui.settings_services import WebUISettingsConfig

    settings = config or WebUISettingsConfig(get_config_path())
    driver = CuaDriver(settings.path)
    existing = settings.load().tools.mcp_servers.get("cua-driver")
    if existing is not None and not driver.owns(existing):
        raise McpPresetError("This Cua Driver connection is managed manually. Its configuration has not been changed.", 409)
    check = None
    reset_permissions = False
    changed = action in {"enable", "disable", "remove", "reconnect", "uninstall"}
    try:
        if action == "install":
            if _query_first(query, "consent") != f"{CUA_CAPABILITY}:install":
                raise McpPresetError("Confirm the driver download and installation on the gateway computer first.", 409)
            await driver.install()
            message = "Computer Use installed and verified. Desktop access is still disabled."
        elif action == "enable":
            mode = _query_first(query, "mode") or ""
            if _query_first(query, "consent") != f"{CUA_CAPABILITY}:{mode}":
                raise McpPresetError("Confirm desktop access on the gateway computer before enabling Cua Driver.", 409)
            server = driver.configuration(mode)
            # Older clients retain their manual setup flow. Only a client that
            # explains the native prompt and supplies this opt-in requests it.
            permissions = _query_first(query, "permissions")
            if permissions:
                if permissions != CUA_PERMISSIONS_CAPABILITY:
                    raise McpPresetError("Confirm the macOS permission request first.", 409)

            def enable(current: Config) -> None:
                saved = current.tools.mcp_servers.get("cua-driver")
                if saved is not None and not driver.owns(saved):
                    raise McpPresetError("The Cua Driver configuration changed. Refresh before continuing.", 409)
                current.tools.mcp_servers["cua-driver"] = server

            # Do not publish a reduced access mode while the previous native
            # process may still accept input. A failed stop preserves the old
            # configuration and its visible access mode for recovery.
            if driver.native:
                await driver.stop()
            await asyncio.to_thread(settings.update, enable)
            if driver.native:
                from nanobot.apps.computer_use_native import clear_pause
                from nanobot.apps.cua_driver_stdio import endpoint

                # Scope belongs to the native process too. Close the old
                # runtime before a confirmed scope change or explicit enable.
                clear_pause(endpoint(settings.path))
            # Persist consent before starting the one native permission flow.
            # The MCP reload reuses that daemon instead of launching a second
            # prompt-capable process. Scope changes do not request OS grants.
            if permissions and existing is None:
                await driver.request_permissions()
            message = "Computer Use enabled. Complete OS permissions on the gateway computer, then check the connection."
        elif action in {"disable", "remove", "uninstall"}:
            if action == "uninstall":
                consent = _query_first(query, "consent")
                if consent not in {CUA_UNINSTALL_CAPABILITY, CUA_UNINSTALL_RESET_CAPABILITY}:
                    raise McpPresetError("Confirm removing this gateway's Computer Use installation first.", 409)
                reset_permissions = consent == CUA_UNINSTALL_RESET_CAPABILITY
                if reset_permissions and not driver.native:
                    raise McpPresetError("Only the independent nanobot Computer Use app can reset its Mac permissions.", 409)
            def disable(current: Config) -> None:
                saved = current.tools.mcp_servers.get("cua-driver")
                if saved is not None and not driver.owns(saved):
                    raise McpPresetError("The Cua Driver configuration changed. Refresh before continuing.", 409)
                current.tools.mcp_servers.pop("cua-driver", None)

            await asyncio.to_thread(settings.update, disable)
            message = "Desktop tools disabled. The installed driver and OS permissions are retained."
        elif action == "reconnect":
            if existing is None:
                raise McpPresetError("Enable Cua Driver before reconnecting.", 409)
            if reload_mcp is None:
                raise McpPresetError("Runtime reconnect is unavailable. Restart nanobot on the gateway computer.", 409)
            # An explicit repair, never a side effect of a background check.
            # Preserve configured scope; do not request new OS permissions.
            await driver.stop()
            if driver.native:
                from nanobot.apps.computer_use_native import clear_pause
                from nanobot.apps.cua_driver_stdio import endpoint

                clear_pause(endpoint(settings.path))
            message = "Reconnected Computer Use with the existing desktop access."
        elif action == "test":
            if existing is None:
                raise McpPresetError("Enable Cua Driver before checking the connection.", 409)
            check = await driver.check()
            message = "Connection checked. This check does not capture your screen or verify model vision."
            # An initial MCP connection can fail while the signed app is waiting
            # for OS grants. Reconnect once the read-only probe confirms them.
            if (not check.get("sharing_paused") and check["connected"] and check["accessibility"] is True
                    and check["screen_recording"] is True and mcp_runtime_status is not None
                    and mcp_runtime_status().get("cua-driver") == "failed"
                    and settings.load().tools.mcp_servers.get("cua-driver") == existing):
                changed = True
        elif action == "setup":
            target = _query_first(query, "target") or ""
            if target == "permissions":
                if existing is None or _query_first(query, "consent") != CUA_PERMISSIONS_CAPABILITY:
                    raise McpPresetError("Enable Cua Driver and confirm the macOS permission request first.", 409)
                await driver.request_permissions()
                message = "Requested permissions on the gateway Mac. Confirm in macOS; no access was granted automatically."
            else:
                await driver.open_setup(target)
                message = "Opened setup on the gateway computer. No permissions were granted."
        else:
            raise McpPresetError("This action is not supported by managed Cua Driver.", 400)
        payload = mcp_presets_payload(
            config_path=settings.path, last_action={"ok": True, "message": message},
        )
        if check is not None:
            payload["last_action"]["driver_check"] = check
        if changed:
            payload["requires_restart"] = True
            try:
                if reload_mcp is not None:
                    result = await reload_mcp(reconnect="cua-driver") if action == "reconnect" else await reload_mcp()
                    payload = attach_mcp_hot_reload_result(payload, result)
                    if action == "reconnect" and result.get("ok"):
                        payload["last_action"]["driver_check"] = await driver.check()
            finally:
                # A failed runtime refresh must not leave the native driver
                # running after the user has removed its configured access.
                if action in {"disable", "remove", "uninstall"}:
                    await driver.stop()
        if action == "uninstall":
            if reset_permissions:
                await driver.uninstall(reset_permissions=True)
            else:
                await driver.uninstall()
            refreshed = mcp_presets_payload(config_path=settings.path, last_action={
                "ok": True, "message": (
                    "Computer Use uninstalled. Its Accessibility and Screen Recording decisions were reset. "
                    "Approve them again after reinstalling. Other apps were not changed."
                    if reset_permissions else "Computer Use uninstalled. macOS permissions and other apps were not changed."
                ),
                "verification": ["config_absent", "managed_package_absent"] + (
                    ["desktop_permissions_reset"] if reset_permissions else []
                ),
            })
            for key in ("hot_reload", "requires_restart"):
                if key in payload:
                    refreshed[key] = payload[key]
            payload = refreshed
        return attach_mcp_runtime_status(
            payload, mcp_runtime_status() if mcp_runtime_status is not None else None,
        )
    except DriverError as exc:
        raise McpPresetError(exc.message, exc.status) from exc
