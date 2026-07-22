"""Small constructors shared by declarative channel manifests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nanobot.channels.contracts import ChannelFieldSpec, FieldKind, SetupRequirement

GROUP_POLICIES = frozenset({"mention", "open", "allowlist"})
DIRECT_GROUP_POLICIES = frozenset({"mention", "open"})


def field(
    kind: FieldKind = "string",
    *,
    choices: Iterable[str] = (),
    default: Any = None,
    writable: bool = True,
    snapshot: bool = True,
    generic_setup: bool = True,
) -> ChannelFieldSpec:
    return ChannelFieldSpec(
        kind=kind,
        choices=frozenset(choices),
        default=default,
        writable=writable,
        snapshot=snapshot,
        generic_setup=generic_setup,
    )


def required(name: str) -> SetupRequirement:
    return SetupRequirement.field(name)


def required_fields(*names: str) -> tuple[SetupRequirement, ...]:
    return tuple(required(name) for name in names)


def one_of(*alternatives: tuple[str, ...]) -> SetupRequirement:
    return SetupRequirement.one_of(*alternatives)
