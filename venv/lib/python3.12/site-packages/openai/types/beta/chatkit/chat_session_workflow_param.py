# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Dict, Union
from typing_extensions import Required, TypedDict

__all__ = ["ChatSessionWorkflowParam", "Tracing"]


class Tracing(TypedDict, total=False):
    """Optional tracing overrides for the workflow invocation.

    When omitted, tracing is enabled by default.
    """

    enabled: bool
    """Whether tracing is enabled during the session. Defaults to true."""


class ChatSessionWorkflowParam(TypedDict, total=False):
    """Workflow reference and overrides applied to the chat session."""

    id: Required[str]
    """Identifier for the workflow invoked by the session."""

    state_variables: Dict[str, Union[str, bool, float]]
    """State variables forwarded to the workflow.

    Keys may be up to 64 characters, values must be primitive types, and the map
    defaults to an empty object.
    """

    tracing: Tracing
    """Optional tracing overrides for the workflow invocation.

    When omitted, tracing is enabled by default.
    """

    version: str
    """Specific workflow version to run. Defaults to the latest deployed version."""
