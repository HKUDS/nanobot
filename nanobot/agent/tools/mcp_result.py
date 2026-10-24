"""Bounded, detached MCP data for host integrations, separate from model text."""

from __future__ import annotations

import json
from typing import Any, cast

from pydantic import BaseModel

_MAX_BYTES = 64 * 1024
_MAX_DEPTH = 16
_MAX_VALUES = 4096


def snapshot_mcp_json(value: Any, max_bytes: int) -> Any:
    pending: list[tuple[Any, int]] = [(value, 0)]
    remaining = _MAX_VALUES
    while pending:
        item, depth = pending.pop()
        remaining -= 1
        if remaining < 0 or depth > _MAX_DEPTH:
            raise ValueError("MCP host data is too complex")
        if isinstance(item, dict):
            mapping = cast(dict[Any, Any], item)
            if len(mapping) > remaining or not all(isinstance(key, str) for key in mapping):
                raise ValueError("MCP host data is not a bounded JSON object")
            pending.extend((child, depth + 1) for child in mapping.values())
            if any(len(key) > max_bytes for key in mapping):
                raise ValueError("MCP host data key is too large")
        elif isinstance(item, list):
            values = cast(list[Any], item)
            if len(values) > remaining:
                raise ValueError("MCP host data array is too large")
            pending.extend((child, depth + 1) for child in values)
        elif isinstance(item, str):
            if len(item) > max_bytes:
                raise ValueError("MCP host data string is too large")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise ValueError("MCP host data is not JSON")

    chunks: list[str] = []
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(value):
        size += len(chunk.encode("utf-8"))
        if size > max_bytes:
            raise ValueError("MCP host data is too large")
        chunks.append(chunk)
    return json.loads("".join(chunks))


def mcp_model_visible(tool_def: Any) -> bool:
    """Honor explicit MCP Apps visibility even without an Apps host."""
    meta = getattr(tool_def, "meta", None)
    if not isinstance(meta, dict):
        return True
    ui: object = cast(dict[str, Any], meta).get("ui")
    if not isinstance(ui, dict):
        return True
    visibility: object = cast(dict[str, Any], ui).get("visibility")
    return visibility is None or (isinstance(visibility, list) and "model" in visibility)


def mcp_host_data(server_name: str, tool_def: Any, result: Any) -> dict[str, Any] | None:
    """Copy rich fields within one byte budget; omit oversized/invalid fields.

    The source identities and wire field names are retained for backend hooks.
    This does not authorize resource reads, tool calls, or browser rendering.
    """
    data: dict[str, Any] = {
        "server_name": server_name,
        "tool_name": tool_def.name,
        "isError": bool(getattr(result, "isError", False)),
    }
    fields: tuple[tuple[str, Any], ...] = (
        ("tool_meta", getattr(tool_def, "meta", None)),
        ("outputSchema", getattr(tool_def, "outputSchema", None)),
        ("annotations", getattr(tool_def, "annotations", None)),
        ("structuredContent", getattr(result, "structuredContent", None)),
        ("_meta", getattr(result, "meta", None)),
        ("content", getattr(result, "content", None)),
    )
    for name, value in fields:
        if value is None:
            continue
        try:
            if isinstance(value, BaseModel):
                value = value.model_dump(mode="python", by_alias=True, exclude_none=True)
            elif name == "content":
                if not isinstance(value, list):
                    continue
                blocks = cast(list[Any], value)
                if len(blocks) > _MAX_VALUES:
                    continue
                value = [
                    block.model_dump(mode="python", by_alias=True, exclude_none=True)
                    if isinstance(block, BaseModel) else block
                    for block in blocks
                ]
            data = snapshot_mcp_json({"mcp": {**data, name: value}}, _MAX_BYTES)["mcp"]
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
            continue
    try:
        return snapshot_mcp_json({"mcp": data}, _MAX_BYTES)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return None
