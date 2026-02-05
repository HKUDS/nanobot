# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Dict, Union, Optional

from ..._models import BaseModel

__all__ = ["ChatKitWorkflow", "Tracing"]


class Tracing(BaseModel):
    """Tracing settings applied to the workflow."""

    enabled: bool
    """Indicates whether tracing is enabled."""


class ChatKitWorkflow(BaseModel):
    """Workflow metadata and state returned for the session."""

    id: str
    """Identifier of the workflow backing the session."""

    state_variables: Optional[Dict[str, Union[str, bool, float]]] = None
    """State variable key-value pairs applied when invoking the workflow.

    Defaults to null when no overrides were provided.
    """

    tracing: Tracing
    """Tracing settings applied to the workflow."""

    version: Optional[str] = None
    """Specific workflow version used for the session.

    Defaults to null when using the latest deployment.
    """
