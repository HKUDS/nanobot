from __future__ import annotations

from typing import Any, cast

from mcp.types import URL_ELICITATION_REQUIRED, ElicitRequestURLParams, ErrorData


class McpError(Exception):
    """
    Exception type raised when an error arrives over an MCP connection.
    """

    error: ErrorData

    def __init__(self, error: ErrorData):
        """Initialize McpError."""
        super().__init__(error.message)
        self.error = error


class UrlElicitationRequiredError(McpError):
    """
    Specialized error for when a tool requires URL mode elicitation(s) before proceeding.

    Servers can raise this error from tool handlers to indicate that the client
    must complete one or more URL elicitations before the request can be processed.

    Example:
        raise UrlElicitationRequiredError([
            ElicitRequestURLParams(
                mode="url",
                message="Authorization required for your files",
                url="https://example.com/oauth/authorize",
                elicitationId="auth-001"
            )
        ])
    """

    def __init__(
        self,
        elicitations: list[ElicitRequestURLParams],
        message: str | None = None,
    ):
        """Initialize UrlElicitationRequiredError."""
        if message is None:
            message = f"URL elicitation{'s' if len(elicitations) > 1 else ''} required"

        self._elicitations = elicitations

        error = ErrorData(
            code=URL_ELICITATION_REQUIRED,
            message=message,
            data={"elicitations": [e.model_dump(by_alias=True, exclude_none=True) for e in elicitations]},
        )
        super().__init__(error)

    @property
    def elicitations(self) -> list[ElicitRequestURLParams]:
        """The list of URL elicitations required before the request can proceed."""
        return self._elicitations

    @classmethod
    def from_error(cls, error: ErrorData) -> UrlElicitationRequiredError:
        """Reconstruct from an ErrorData received over the wire."""
        if error.code != URL_ELICITATION_REQUIRED:
            raise ValueError(f"Expected error code {URL_ELICITATION_REQUIRED}, got {error.code}")

        data = cast(dict[str, Any], error.data or {})
        raw_elicitations = cast(list[dict[str, Any]], data.get("elicitations", []))
        elicitations = [ElicitRequestURLParams.model_validate(e) for e in raw_elicitations]
        return cls(elicitations, error.message)
