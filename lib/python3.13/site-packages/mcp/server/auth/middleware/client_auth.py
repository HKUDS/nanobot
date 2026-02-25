import base64
import binascii
import hmac
import time
from typing import Any
from urllib.parse import unquote

from starlette.requests import Request

from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.shared.auth import OAuthClientInformationFull


class AuthenticationError(Exception):
    def __init__(self, message: str):
        self.message = message  # pragma: no cover


class ClientAuthenticator:
    """
    ClientAuthenticator is a callable which validates requests from a client
    application, used to verify /token calls.
    If, during registration, the client requested to be issued a secret, the
    authenticator asserts that /token calls must be authenticated with
    that same token.
    NOTE: clients can opt for no authentication during registration, in which case this
    logic is skipped.
    """

    def __init__(self, provider: OAuthAuthorizationServerProvider[Any, Any, Any]):
        """
        Initialize the dependency.

        Args:
            provider: Provider to look up client information
        """
        self.provider = provider

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        """
        Authenticate a client from an HTTP request.

        Extracts client credentials from the appropriate location based on the
        client's registered authentication method and validates them.

        Args:
            request: The HTTP request containing client credentials

        Returns:
            The authenticated client information

        Raises:
            AuthenticationError: If authentication fails
        """
        form_data = await request.form()
        client_id = form_data.get("client_id")
        if not client_id:
            raise AuthenticationError("Missing client_id")

        client = await self.provider.get_client(str(client_id))
        if not client:
            raise AuthenticationError("Invalid client_id")  # pragma: no cover

        request_client_secret: str | None = None
        auth_header = request.headers.get("Authorization", "")

        if client.token_endpoint_auth_method == "client_secret_basic":
            if not auth_header.startswith("Basic "):
                raise AuthenticationError("Missing or invalid Basic authentication in Authorization header")

            try:
                encoded_credentials = auth_header[6:]  # Remove "Basic " prefix
                decoded = base64.b64decode(encoded_credentials).decode("utf-8")
                if ":" not in decoded:
                    raise ValueError("Invalid Basic auth format")
                basic_client_id, request_client_secret = decoded.split(":", 1)

                # URL-decode both parts per RFC 6749 Section 2.3.1
                basic_client_id = unquote(basic_client_id)
                request_client_secret = unquote(request_client_secret)

                if basic_client_id != client_id:
                    raise AuthenticationError("Client ID mismatch in Basic auth")
            except (ValueError, UnicodeDecodeError, binascii.Error):
                raise AuthenticationError("Invalid Basic authentication header")

        elif client.token_endpoint_auth_method == "client_secret_post":
            raw_form_data = form_data.get("client_secret")
            # form_data.get() can return a UploadFile or None, so we need to check if it's a string
            if isinstance(raw_form_data, str):
                request_client_secret = str(raw_form_data)

        elif client.token_endpoint_auth_method == "none":
            request_client_secret = None
        else:
            raise AuthenticationError(  # pragma: no cover
                f"Unsupported auth method: {client.token_endpoint_auth_method}"
            )

        # If client from the store expects a secret, validate that the request provides
        # that secret
        if client.client_secret:  # pragma: no branch
            if not request_client_secret:
                raise AuthenticationError("Client secret is required")  # pragma: no cover

            # hmac.compare_digest requires that both arguments are either bytes or a `str` containing
            # only ASCII characters. Since we do not control `request_client_secret`, we encode both
            # arguments to bytes.
            if not hmac.compare_digest(client.client_secret.encode(), request_client_secret.encode()):
                raise AuthenticationError("Invalid client_secret")  # pragma: no cover

            if client.client_secret_expires_at and client.client_secret_expires_at < int(time.time()):
                raise AuthenticationError("Client secret has expired")  # pragma: no cover

        return client
