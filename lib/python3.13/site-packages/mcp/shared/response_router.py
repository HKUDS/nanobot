"""
ResponseRouter - Protocol for pluggable response routing.

This module defines a protocol for routing JSON-RPC responses to alternative
handlers before falling back to the default response stream mechanism.

The primary use case is task-augmented requests: when a TaskSession enqueues
a request (like elicitation), the response needs to be routed back to the
waiting resolver instead of the normal response stream.

Design:
- Protocol-based for testability and flexibility
- Returns bool to indicate if response was handled
- Supports both success responses and errors
"""

from typing import Any, Protocol

from mcp.types import ErrorData, RequestId


class ResponseRouter(Protocol):
    """
    Protocol for routing responses to alternative handlers.

    Implementations check if they have a pending request for the given ID
    and deliver the response/error to the appropriate handler.

    Example:
        class TaskResultHandler(ResponseRouter):
            def route_response(self, request_id, response):
                resolver = self._pending_requests.pop(request_id, None)
                if resolver:
                    resolver.set_result(response)
                    return True
                return False
    """

    def route_response(self, request_id: RequestId, response: dict[str, Any]) -> bool:
        """
        Try to route a response to a pending request handler.

        Args:
            request_id: The JSON-RPC request ID from the response
            response: The response result data

        Returns:
            True if the response was handled, False otherwise
        """
        ...  # pragma: no cover

    def route_error(self, request_id: RequestId, error: ErrorData) -> bool:
        """
        Try to route an error to a pending request handler.

        Args:
            request_id: The JSON-RPC request ID from the error response
            error: The error data

        Returns:
            True if the error was handled, False otherwise
        """
        ...  # pragma: no cover
