"""Provider-neutral errors raised by structured decision operations."""


class StructuredDecisionError(Exception):
    """Base error for structured decision failures."""


class MissingCredentialsError(StructuredDecisionError):
    """Raised when the selected provider has no configured credentials."""


class DecisionHttpError(StructuredDecisionError):
    """Raised when a decision endpoint returns an HTTP error."""

    def __init__(self, status_code: int | None, reason: str | None = None):
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"HTTP {status_code} {reason or ''}".strip())


class DecisionTransportError(StructuredDecisionError):
    """Raised when the underlying async transport fails."""


class DecisionClientClosedError(StructuredDecisionError):
    """Raised when a decision client is used after it has been closed."""


class DecisionTimeoutError(StructuredDecisionError):
    """Raised when a decision request times out."""


class MalformedDecisionJsonError(StructuredDecisionError):
    """Raised when the response body is not valid JSON."""


class DecisionProtocolError(StructuredDecisionError):
    """Raised when a request or response does not match the protocol."""


class IncompleteDecisionResponseError(DecisionProtocolError):
    """Raised when a response is missing required data."""


class UnsupportedDecisionProviderError(StructuredDecisionError):
    """Raised when no decision endpoint is registered for a provider."""


class UnsupportedDecisionProtocolError(StructuredDecisionError):
    """Raised when a provider does not support the requested protocol."""
