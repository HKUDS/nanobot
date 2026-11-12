"""Typed loader for the bundled MCP service catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Literal

from pydantic import TypeAdapter

from nanobot.config.schema import MCPServerConfig


@dataclass(frozen=True)
class McpPresetField:
    name: str
    label: str
    target: tuple[Literal["env", "url_param", "arg", "header", "url"], str]
    secret: bool = True
    required: bool = True
    env_var: str | None = None
    placeholder: str = ""
    value_prefix: str = ""


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


def _parse_presets(data: str) -> tuple[McpPreset, ...]:
    presets = TypeAdapter(tuple[McpPreset, ...]).validate_json(data, strict=True, extra="forbid")
    names: set[str] = set()
    for preset in presets:
        if preset.name in names:
            raise ValueError(f"Duplicate MCP preset name: {preset.name}")
        names.add(preset.name)
    return presets


MCP_PRESETS = _parse_presets(
    files("nanobot.webui").joinpath("mcp_presets.json").read_text(encoding="utf-8")
)
