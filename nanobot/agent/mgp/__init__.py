"""MGP sidecar package for nanobot. Opt-in; only imported when ``mgp.enabled = true``.

Importing this module is cheap: the optional ``mgp-client`` dependency is
checked lazily inside :func:`build_sidecar`. The dataclasses re-exported
below are safe to import without ``mgp-client``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    CommitOutcome,
    ParsedFact,
    RecallIntent,
    RecallItem,
    RecallOutcome,
    RuntimeState,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only
    from nanobot.config.schema import MGPConfig

    from .sidecar import AsyncMGPSidecar


class MGPSidecarUnavailable(RuntimeError):
    """Raised when the MGP sidecar is requested but ``mgp-client`` is not installed."""


def build_sidecar(config: "MGPConfig", *, workspace_id: str | None = None) -> "AsyncMGPSidecar":
    """Build an :class:`AsyncMGPSidecar`, importing ``mgp_client`` lazily."""
    try:
        import mgp_client  # noqa: F401  (probe import only)
    except ImportError as exc:
        raise MGPSidecarUnavailable(
            "mgp-client is not installed. Install with: pip install 'nanobot[mgp]'"
        ) from exc

    from .sidecar import AsyncMGPSidecar

    return AsyncMGPSidecar(config, workspace_id=workspace_id)


__all__ = [
    "CommitOutcome",
    "MGPSidecarUnavailable",
    "ParsedFact",
    "RecallIntent",
    "RecallItem",
    "RecallOutcome",
    "RuntimeState",
    "build_sidecar",
]
