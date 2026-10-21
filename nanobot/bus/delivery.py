"""Delivery correlation and pre-send failure contracts, independent of transports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

DELIVERY_RUN_META = "_delivery_run_id"


class ChannelNotReadyError(RuntimeError):
    """No part of the message was sent; retry after the channel reconnects."""


class DeliveryRejectedError(RuntimeError):
    """No part of the message was sent; configuration or destination needs repair."""


@dataclass(frozen=True)
class DeliveryRequest:
    """A scheduled result belongs to one run and one admitted source session."""

    run_id: str
    session_key: str
    session_generation: str | None

    @classmethod
    def from_context(
        cls, metadata: Mapping[str, object], session_key: str | None, generation: str | None,
    ) -> DeliveryRequest | None:
        run_id = metadata.get(DELIVERY_RUN_META)
        if not isinstance(run_id, str) or not run_id:
            return None
        if not session_key:
            raise ValueError("Scheduled delivery requires a source session")
        return cls(run_id, session_key, generation)
