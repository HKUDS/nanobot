# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, TypeAlias, TypedDict

__all__ = ["RealtimeTracingConfigParam", "TracingConfiguration"]


class TracingConfiguration(TypedDict, total=False):
    """Granular configuration for tracing."""

    group_id: str
    """
    The group id to attach to this trace to enable filtering and grouping in the
    Traces Dashboard.
    """

    metadata: object
    """
    The arbitrary metadata to attach to this trace to enable filtering in the Traces
    Dashboard.
    """

    workflow_name: str
    """The name of the workflow to attach to this trace.

    This is used to name the trace in the Traces Dashboard.
    """


RealtimeTracingConfigParam: TypeAlias = Union[Literal["auto"], TracingConfiguration]
