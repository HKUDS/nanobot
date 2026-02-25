# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal, TypeAlias

from ..._models import BaseModel

__all__ = ["RealtimeTracingConfig", "TracingConfiguration"]


class TracingConfiguration(BaseModel):
    """Granular configuration for tracing."""

    group_id: Optional[str] = None
    """
    The group id to attach to this trace to enable filtering and grouping in the
    Traces Dashboard.
    """

    metadata: Optional[object] = None
    """
    The arbitrary metadata to attach to this trace to enable filtering in the Traces
    Dashboard.
    """

    workflow_name: Optional[str] = None
    """The name of the workflow to attach to this trace.

    This is used to name the trace in the Traces Dashboard.
    """


RealtimeTracingConfig: TypeAlias = Union[Literal["auto"], TracingConfiguration, None]
