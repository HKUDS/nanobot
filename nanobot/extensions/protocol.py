"""Versioned messages shared with the Node compatibility sidecar."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

NODE_PROTOCOL_VERSION = 1
_CALLABLE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class NodeProtocolError(RuntimeError):
    """The sidecar returned an invalid message or reported an RPC failure."""


@dataclass(frozen=True, slots=True)
class NodeRegistration:
    """One callable or inspectable contribution retained by the sidecar."""

    kind: str
    name: str
    description: str = ""
    schema: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, value: object) -> NodeRegistration:
        if not isinstance(value, dict):
            raise NodeProtocolError("sidecar registration must be an object")
        kind = value.get("kind")
        name = value.get("name")
        if (
            not isinstance(kind, str)
            or not isinstance(name, str)
            or not kind.strip()
            or not name.strip()
        ):
            raise NodeProtocolError("sidecar registration requires non-empty string kind and name")
        schema = value.get("schema")
        metadata = value.get("metadata")
        if schema is not None and not isinstance(schema, dict):
            raise NodeProtocolError("sidecar registration schema must be an object")
        if metadata is not None and not isinstance(metadata, dict):
            raise NodeProtocolError("sidecar registration metadata must be an object")
        if kind in {"tool", "command"}:
            if not _CALLABLE_NAME.fullmatch(name):
                raise NodeProtocolError(
                    f"sidecar {kind} name {name!r} must match "
                    "[A-Za-z0-9_-] and be at most 64 characters"
                )
            if (
                kind == "tool"
                and schema is not None
                and schema.get("type", "object") != "object"
            ):
                raise NodeProtocolError(
                    f"sidecar tool {name!r} parameters must use an object schema"
                )
        return cls(
            kind=kind,
            name=name,
            description=str(value.get("description") or ""),
            schema=schema,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class NodeLoadResult:
    """Metadata returned after a Pi or OpenClaw module registers itself."""

    registrations: tuple[NodeRegistration, ...]
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: object) -> NodeLoadResult:
        if not isinstance(value, dict):
            raise NodeProtocolError("sidecar load result must be an object")
        registrations = value.get("registrations", [])
        diagnostics = value.get("diagnostics", [])
        if not isinstance(registrations, list) or not isinstance(diagnostics, list):
            raise NodeProtocolError("invalid sidecar load result")
        return cls(
            registrations=tuple(NodeRegistration.from_mapping(item) for item in registrations),
            diagnostics=tuple(str(item) for item in diagnostics),
        )
