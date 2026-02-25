"""
OAuth2 Authentication implementation for HTTPX.

Implements authorization code flow with PKCE and automatic token refresh.
"""

import base64
import hashlib
import logging
import secrets
import string
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urljoin, urlparse

import anyio
import httpx
from pydantic import BaseModel, Field, ValidationError

from mcp.client.auth.exceptions import OAuthFlowError, OAuthTokenError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_client_info_from_metadata_url,
    create_client_registration_request,
    create_oauth_metadata_request,
    extract_field_from_www_auth,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    get_client_metadata_scopes,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    handle_registration_response,
    handle_token_response_scopes,
    is_valid_client_metadata_url,
    should_use_client_metadata_url,
)
from mcp.client.streamable_http import MCP_PROTOCOL_VERSION
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from mcp.shared.auth_utils import (
    calculate_token_expiry,
    check_resource_allowed,
    resource_url_from_server_url,
)

logger = logging.getLogger(__name__)


class PKCEParameters(BaseModel):
    """PKCE (Proof Key for Code Exchange) parameters."""

    code_verifier: str = Field(..., min_length=43, max_length=128)
    code_challenge: str = Field(..., min_length=43, max_length=128)

    @classmethod
    def generate(cls) -> "PKCEParameters":
        """Generate new PKCE parameters."""
        code_verifier = "".join(secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(128))
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return cls(code_verifier=code_verifier, code_challenge=code_challenge)


class TokenStorage(Protocol):
    """Protocol for token storage implementations."""

    async def get_tokens(self) -> OAuthToken | None:
        """Get stored tokens."""
        ...

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store tokens."""
        ...

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Get stored client information."""
        ...

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store client information."""
        ...


@dataclass
class OAuthContext:
    """OAuth flow context."""

    server_url: str
    client_metadata: OAuthClientMetadata
    storage: TokenStorage
    redirect_handler: Callable[[str], Awaitable[None]] | None
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None
    timeout: float = 300.0
    client_metadata_url: str | None = None

    # Discovered metadata
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    oauth_metadata: OAuthMetadata | None = None
    auth_server_url: str | None = None
    protocol_version: str | None = None

    # Client registration
    client_info: OAuthClientInformationFull | None = None

    # Token management
    current_tokens: OAuthToken | None = None
    token_expiry_time: float | None = None

    # State
    lock: anyio.Lock = field(default_factory=anyio.Lock)

    def get_authorization_base_url(self, server_url: str) -> str:
        """Extract base URL by removing path component."""
        parsed = urlparse(server_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def update_token_expiry(self, token: OAuthToken) -> None:
        """Update token expiry time using shared util function."""
        self.token_expiry_time = calculate_token_expiry(token.expires_in)

    def is_token_valid(self) -> bool:
        """Check if current token is valid."""
        return bool(
            self.current_tokens
            and self.current_tokens.access_token
            and (not self.token_expiry_time or time.time() <= self.token_expiry_time)
        )

    def can_refresh_token(self) -> bool:
        """Check if token can be refreshed."""
        return bool(self.current_tokens and self.current_tokens.refresh_token and self.client_info)

    def clear_tokens(self) -> None:
        """Clear current tokens."""
        self.current_tokens = None
        self.token_expiry_time = None

    def get_resource_url(self) -> str:
        """Get resource URL for RFC 8707.

        Uses PRM resource if it's a valid parent, otherwise uses canonical server URL.
        """
        resource = resource_url_from_server_url(self.server_url)

        # If PRM provides a resource that's a valid parent, use it
        if self.protected_resource_metadata and self.protected_resource_metadata.resource:
            prm_resource = str(self.protected_resource_metadata.resource)
            if check_resource_allowed(requested_resource=resource, configured_resource=prm_resource):
                resource = prm_resource

        return resource

    def should_include_resource_param(self, protocol_version: str | None = None) -> bool:
        """Determine if the resource parameter should be included in OAuth requests.

        Returns True if:
        - Protected resource metadata is available, OR
        - MCP-Protocol-Version header is 2025-06-18 or later
        """
        # If we have protected resource metadata, include the resource param
        if self.protected_resource_metadata is not None:
            return True

        # If no protocol version provided, don't include resource param
        if not protocol_version:
            return False

        # Check if protocol version is 2025-06-18 or later
        # Version format is YYYY-MM-DD, so string comparison works
        return protocol_version >= "2025-06-18"

    def prepare_token_auth(
        self, data: dict[str, str], headers: dict[str, str] | None = None
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Prepare authentication for token requests.

        Args:
            data: The form data to send
            headers: Optional headers dict to update

        Returns:
            Tuple of (updated_data, updated_headers)
        """
        if headers is None:
            headers = {}  # pragma: no cover

        if not self.client_info:
            return data, headers  # pragma: no cover

        auth_method = self.client_info.token_endpoint_auth_method

        if auth_method == "client_secret_basic" and self.client_info.client_id and self.client_info.client_secret:
            # URL-encode client ID and secret per RFC 6749 Section 2.3.1
            encoded_id = quote(self.client_info.client_id, safe="")
            encoded_secret = quote(self.client_info.client_secret, safe="")
            credentials = f"{encoded_id}:{encoded_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded_credentials}"
            # Don't include client_secret in body for basic auth
            data = {k: v for k, v in data.items() if k != "client_secret"}
        elif auth_method == "client_secret_post" and self.client_info.client_secret:
            # Include client_secret in request body
            data["client_secret"] = self.client_info.client_secret
        # For auth_method == "none", don't add any client_secret

        return data, headers


class OAuthClientProvider(httpx.Auth):
    """
    OAuth2 authentication for httpx.
    Handles OAuth flow with automatic client registration and token storage.
    """

    requires_response_body = True

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,
        client_metadata_url: str | None = None,
    ):
        """Initialize OAuth2 authentication.

        Args:
            server_url: The MCP server URL.
            client_metadata: OAuth client metadata for registration.
            storage: Token storage implementation.
            redirect_handler: Handler for authorization redirects.
            callback_handler: Handler for authorization callbacks.
            timeout: Timeout for the OAuth flow.
            client_metadata_url: URL-based client ID. When provided and the server
                advertises client_id_metadata_document_supported=true, this URL will be
                used as the client_id instead of performing dynamic client registration.
                Must be a valid HTTPS URL with a non-root pathname.

        Raises:
            ValueError: If client_metadata_url is provided but not a valid HTTPS URL
                with a non-root pathname.
        """
        # Validate client_metadata_url if provided
        if client_metadata_url is not None and not is_valid_client_metadata_url(client_metadata_url):
            raise ValueError(
                f"client_metadata_url must be a valid HTTPS URL with a non-root pathname, got: {client_metadata_url}"
            )

        self.context = OAuthContext(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=timeout,
            client_metadata_url=client_metadata_url,
        )
        self._initialized = False

    async def _handle_protected_resource_response(self, response: httpx.Response) -> bool:
        """
        Handle protected resource metadata discovery response.

        Per SEP-985, supports fallback when discovery fails at one URL.

        Returns:
            True if metadata was successfully discovered, False if we should try next URL
        """
        if response.status_code == 200:
            try:
                content = await response.aread()
                metadata = ProtectedResourceMetadata.model_validate_json(content)
                self.context.protected_resource_metadata = metadata
                if metadata.authorization_servers:  # pragma: no branch
                    self.context.auth_server_url = str(metadata.authorization_servers[0])
                return True

            except ValidationError:  # pragma: no cover
                # Invalid metadata - try next URL
                logger.warning(f"Invalid protected resource metadata at {response.request.url}")
                return False
        elif response.status_code == 404:  # pragma: no cover
            # Not found - try next URL in fallback chain
            logger.debug(f"Protected resource metadata not found at {response.request.url}, trying next URL")
            return False
        else:
            # Other error - fail immediately
            raise OAuthFlowError(
                f"Protected Resource Metadata request failed: {response.status_code}"
            )  # pragma: no cover

    async def _perform_authorization(self) -> httpx.Request:
        """Perform the authorization flow."""
        auth_code, code_verifier = await self._perform_authorization_code_grant()
        token_request = await self._exchange_token_authorization_code(auth_code, code_verifier)
        return token_request

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        """Perform the authorization redirect and get auth code."""
        if self.context.client_metadata.redirect_uris is None:
            raise OAuthFlowError("No redirect URIs provided for authorization code grant")  # pragma: no cover
        if not self.context.redirect_handler:
            raise OAuthFlowError("No redirect handler provided for authorization code grant")  # pragma: no cover
        if not self.context.callback_handler:
            raise OAuthFlowError("No callback handler provided for authorization code grant")  # pragma: no cover

        if self.context.oauth_metadata and self.context.oauth_metadata.authorization_endpoint:
            auth_endpoint = str(self.context.oauth_metadata.authorization_endpoint)  # pragma: no cover
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            auth_endpoint = urljoin(auth_base_url, "/authorize")

        if not self.context.client_info:
            raise OAuthFlowError("No client info available for authorization")  # pragma: no cover

        # Generate PKCE parameters
        pkce_params = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)

        auth_params = {
            "response_type": "code",
            "client_id": self.context.client_info.client_id,
            "redirect_uri": str(self.context.client_metadata.redirect_uris[0]),
            "state": state,
            "code_challenge": pkce_params.code_challenge,
            "code_challenge_method": "S256",
        }

        # Only include resource param if conditions are met
        if self.context.should_include_resource_param(self.context.protocol_version):
            auth_params["resource"] = self.context.get_resource_url()  # RFC 8707  # pragma: no cover

        if self.context.client_metadata.scope:  # pragma: no branch
            auth_params["scope"] = self.context.client_metadata.scope

        authorization_url = f"{auth_endpoint}?{urlencode(auth_params)}"
        await self.context.redirect_handler(authorization_url)

        # Wait for callback
        auth_code, returned_state = await self.context.callback_handler()

        if returned_state is None or not secrets.compare_digest(returned_state, state):
            raise OAuthFlowError(f"State parameter mismatch: {returned_state} != {state}")  # pragma: no cover

        if not auth_code:
            raise OAuthFlowError("No authorization code received")  # pragma: no cover

        # Return auth code and code verifier for token exchange
        return auth_code, pkce_params.code_verifier

    def _get_token_endpoint(self) -> str:
        if self.context.oauth_metadata and self.context.oauth_metadata.token_endpoint:
            token_url = str(self.context.oauth_metadata.token_endpoint)
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            token_url = urljoin(auth_base_url, "/token")
        return token_url

    async def _exchange_token_authorization_code(
        self, auth_code: str, code_verifier: str, *, token_data: dict[str, Any] | None = {}
    ) -> httpx.Request:
        """Build token exchange request for authorization_code flow."""
        if self.context.client_metadata.redirect_uris is None:
            raise OAuthFlowError("No redirect URIs provided for authorization code grant")  # pragma: no cover
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info")  # pragma: no cover

        token_url = self._get_token_endpoint()
        token_data = token_data or {}
        token_data.update(
            {
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": str(self.context.client_metadata.redirect_uris[0]),
                "client_id": self.context.client_info.client_id,
                "code_verifier": code_verifier,
            }
        )

        # Only include resource param if conditions are met
        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()  # RFC 8707

        # Prepare authentication based on preferred method
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        return httpx.Request("POST", token_url, data=token_data, headers=headers)

    async def _handle_token_response(self, response: httpx.Response) -> None:
        """Handle token exchange response."""
        if response.status_code != 200:
            body = await response.aread()  # pragma: no cover
            body_text = body.decode("utf-8")  # pragma: no cover
            raise OAuthTokenError(f"Token exchange failed ({response.status_code}): {body_text}")  # pragma: no cover

        # Parse and validate response with scope validation
        token_response = await handle_token_response_scopes(response)

        # Store tokens in context
        self.context.current_tokens = token_response
        self.context.update_token_expiry(token_response)
        await self.context.storage.set_tokens(token_response)

    async def _refresh_token(self) -> httpx.Request:
        """Build token refresh request."""
        if not self.context.current_tokens or not self.context.current_tokens.refresh_token:
            raise OAuthTokenError("No refresh token available")  # pragma: no cover

        if not self.context.client_info or not self.context.client_info.client_id:
            raise OAuthTokenError("No client info available")  # pragma: no cover

        if self.context.oauth_metadata and self.context.oauth_metadata.token_endpoint:
            token_url = str(self.context.oauth_metadata.token_endpoint)  # pragma: no cover
        else:
            auth_base_url = self.context.get_authorization_base_url(self.context.server_url)
            token_url = urljoin(auth_base_url, "/token")

        refresh_data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": self.context.current_tokens.refresh_token,
            "client_id": self.context.client_info.client_id,
        }

        # Only include resource param if conditions are met
        if self.context.should_include_resource_param(self.context.protocol_version):
            refresh_data["resource"] = self.context.get_resource_url()  # RFC 8707

        # Prepare authentication based on preferred method
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        refresh_data, headers = self.context.prepare_token_auth(refresh_data, headers)

        return httpx.Request("POST", token_url, data=refresh_data, headers=headers)

    async def _handle_refresh_response(self, response: httpx.Response) -> bool:  # pragma: no cover
        """Handle token refresh response. Returns True if successful."""
        if response.status_code != 200:
            logger.warning(f"Token refresh failed: {response.status_code}")
            self.context.clear_tokens()
            return False

        try:
            content = await response.aread()
            token_response = OAuthToken.model_validate_json(content)

            self.context.current_tokens = token_response
            self.context.update_token_expiry(token_response)
            await self.context.storage.set_tokens(token_response)

            return True
        except ValidationError:
            logger.exception("Invalid refresh response")
            self.context.clear_tokens()
            return False

    async def _initialize(self) -> None:  # pragma: no cover
        """Load stored tokens and client info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = await self.context.storage.get_client_info()
        self._initialized = True

    def _add_auth_header(self, request: httpx.Request) -> None:
        """Add authorization header to request if we have valid tokens."""
        if self.context.current_tokens and self.context.current_tokens.access_token:  # pragma: no branch
            request.headers["Authorization"] = f"Bearer {self.context.current_tokens.access_token}"

    async def _handle_oauth_metadata_response(self, response: httpx.Response) -> None:
        content = await response.aread()
        metadata = OAuthMetadata.model_validate_json(content)
        self.context.oauth_metadata = metadata

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX auth flow integration."""
        async with self.context.lock:
            if not self._initialized:
                await self._initialize()  # pragma: no cover

            # Capture protocol version from request headers
            self.context.protocol_version = request.headers.get(MCP_PROTOCOL_VERSION)

            if not self.context.is_token_valid() and self.context.can_refresh_token():
                # Try to refresh token
                refresh_request = await self._refresh_token()  # pragma: no cover
                refresh_response = yield refresh_request  # pragma: no cover

                if not await self._handle_refresh_response(refresh_response):  # pragma: no cover
                    # Refresh failed, need full re-authentication
                    self._initialized = False

            if self.context.is_token_valid():
                self._add_auth_header(request)

            response = yield request

            if response.status_code == 401:
                # Perform full OAuth flow
                try:
                    # OAuth flow must be inline due to generator constraints
                    www_auth_resource_metadata_url = extract_resource_metadata_from_www_auth(response)

                    # Step 1: Discover protected resource metadata (SEP-985 with fallback support)
                    prm_discovery_urls = build_protected_resource_metadata_discovery_urls(
                        www_auth_resource_metadata_url, self.context.server_url
                    )

                    for url in prm_discovery_urls:  # pragma: no branch
                        discovery_request = create_oauth_metadata_request(url)

                        discovery_response = yield discovery_request  # sending request

                        prm = await handle_protected_resource_response(discovery_response)
                        if prm:
                            self.context.protected_resource_metadata = prm

                            # todo: try all authorization_servers to find the OASM
                            assert (
                                len(prm.authorization_servers) > 0
                            )  # this is always true as authorization_servers has a min length of 1

                            self.context.auth_server_url = str(prm.authorization_servers[0])
                            break
                        else:
                            logger.debug(f"Protected resource metadata discovery failed: {url}")

                    asm_discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(
                        self.context.auth_server_url, self.context.server_url
                    )

                    # Step 2: Discover OAuth Authorization Server Metadata (OASM) (with fallback for legacy servers)
                    for url in asm_discovery_urls:  # pragma: no cover
                        oauth_metadata_request = create_oauth_metadata_request(url)
                        oauth_metadata_response = yield oauth_metadata_request

                        ok, asm = await handle_auth_metadata_response(oauth_metadata_response)
                        if not ok:
                            break
                        if ok and asm:
                            self.context.oauth_metadata = asm
                            break
                        else:
                            logger.debug(f"OAuth metadata discovery failed: {url}")

                    # Step 3: Apply scope selection strategy
                    self.context.client_metadata.scope = get_client_metadata_scopes(
                        extract_scope_from_www_auth(response),
                        self.context.protected_resource_metadata,
                        self.context.oauth_metadata,
                    )

                    # Step 4: Register client or use URL-based client ID (CIMD)
                    if not self.context.client_info:
                        if should_use_client_metadata_url(
                            self.context.oauth_metadata, self.context.client_metadata_url
                        ):
                            # Use URL-based client ID (CIMD)
                            logger.debug(f"Using URL-based client ID (CIMD): {self.context.client_metadata_url}")
                            client_information = create_client_info_from_metadata_url(
                                self.context.client_metadata_url,  # type: ignore[arg-type]
                                redirect_uris=self.context.client_metadata.redirect_uris,
                            )
                            self.context.client_info = client_information
                            await self.context.storage.set_client_info(client_information)
                        else:
                            # Fallback to Dynamic Client Registration
                            registration_request = create_client_registration_request(
                                self.context.oauth_metadata,
                                self.context.client_metadata,
                                self.context.get_authorization_base_url(self.context.server_url),
                            )
                            registration_response = yield registration_request
                            client_information = await handle_registration_response(registration_response)
                            self.context.client_info = client_information
                            await self.context.storage.set_client_info(client_information)

                    # Step 5: Perform authorization and complete token exchange
                    token_response = yield await self._perform_authorization()
                    await self._handle_token_response(token_response)
                except Exception:  # pragma: no cover
                    logger.exception("OAuth flow error")
                    raise

                # Retry with new tokens
                self._add_auth_header(request)
                yield request
            elif response.status_code == 403:
                # Step 1: Extract error field from WWW-Authenticate header
                error = extract_field_from_www_auth(response, "error")

                # Step 2: Check if we need to step-up authorization
                if error == "insufficient_scope":  # pragma: no branch
                    try:
                        # Step 2a: Update the required scopes
                        self.context.client_metadata.scope = get_client_metadata_scopes(
                            extract_scope_from_www_auth(response), self.context.protected_resource_metadata
                        )

                        # Step 2b: Perform (re-)authorization and token exchange
                        token_response = yield await self._perform_authorization()
                        await self._handle_token_response(token_response)
                    except Exception:  # pragma: no cover
                        logger.exception("OAuth flow error")
                        raise

                # Retry with new tokens
                self._add_auth_header(request)
                yield request
