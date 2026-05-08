"""Metadata schemas for the CRM MCP server skeleton."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    read_only: bool
    description: str


@dataclass(frozen=True)
class RuntimeMetadata:
    real_crm_access_enabled: bool = False
    requires_endpoint: bool = False
    requires_token: bool = False
    network_enabled: bool = False


@dataclass(frozen=True)
class ServerMetadata:
    name: str
    version: str
    description: str
    tools: tuple[ToolMetadata, ...]


@dataclass(frozen=True)
class ServerSkeleton:
    metadata: ServerMetadata
    runtime: RuntimeMetadata
