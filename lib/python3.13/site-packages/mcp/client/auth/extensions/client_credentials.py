"""
OAuth client credential extensions for MCP.

Provides OAuth providers for machine-to-machine authentication flows:
- ClientCredentialsOAuthProvider: For client_credentials with client_id + client_secret
- PrivateKeyJWTOAuthProvider: For client_credentials with private_key_jwt authentication
  (typically using a pre-built JWT from workload identity federation)
- RFC7523OAuthClientProvider: For jwt-bearer grant (RFC 7523 Section 2.1)
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import uuid4

import httpx
import jwt
from pydantic import BaseModel, Field

from mcp.client.auth import OAuthClientProvider, OAuthFlowError, OAuthTokenError, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata


class ClientCredentialsOAuthProvider(OAuthClientProvider):
    """OAuth provider for client_credentials grant with client_id + client_secret.

    This provider sets client_info directly, bypassing dynamic client registration.
    Use this when you already have client credentials (client_id and client_secret).

    Example:
        ```python
        provider = ClientCredentialsOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            client_secret="my-client-secret",
        )
        ```
    """

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        client_secret: str,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic",
        scopes: str | None = None,
    ) -> None:
        """Initialize client_credentials OAuth provider.

        Args:
            server_url: The MCP server URL.
            storage: Token storage implementation.
            client_id: The OAuth client ID.
            client_secret: The OAuth client secret.
            token_endpoint_auth_method: Authentication method for token endpoint.
                Either "client_secret_basic" (default) or "client_secret_post".
            scopes: Optional space-separated list of scopes to request.
        """
        # Build minimal client_metadata for the base class
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=["client_credentials"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        super().__init__(server_url, client_metadata, storage, None, None, 300.0)
        # Store client_info to be set during _initialize - no dynamic registration needed
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            client_secret=client_secret,
            grant_types=["client_credentials"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )

    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    async def _perform_authorization(self) -> httpx.Request:
        """Perform client_credentials authorization."""
        return await self._exchange_token_client_credentials()

    async def _exchange_token_client_credentials(self) -> httpx.Request:
        """Build token exchange request for client_credentials grant."""
        token_data: dict[str, Any] = {
            "grant_type": "client_credentials",
        }

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

        # Use standard auth methods (client_secret_basic, client_secret_post, none)
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx.Request("POST", token_url, data=token_data, headers=headers)


def static_assertion_provider(token: str) -> Callable[[str], Awaitable[str]]:
    """Create an assertion provider that returns a static JWT token.

    Use this when you have a pre-built JWT (e.g., from workload identity federation)
    that doesn't need the audience parameter.

    Example:
        ```python
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=static_assertion_provider(my_prebuilt_jwt),
        )
        ```

    Args:
        token: The pre-built JWT assertion string.

    Returns:
        An async callback suitable for use as an assertion_provider.
    """

    async def provider(audience: str) -> str:
        return token

    return provider


class SignedJWTParameters(BaseModel):
    """Parameters for creating SDK-signed JWT assertions.

    Use `create_assertion_provider()` to create an assertion provider callback
    for use with `PrivateKeyJWTOAuthProvider`.

    Example:
        ```python
        jwt_params = SignedJWTParameters(
            issuer="my-client-id",
            subject="my-client-id",
            signing_key=private_key_pem,
        )
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=jwt_params.create_assertion_provider(),
        )
        ```
    """

    issuer: str = Field(description="Issuer for JWT assertions (typically client_id).")
    subject: str = Field(description="Subject identifier for JWT assertions (typically client_id).")
    signing_key: str = Field(description="Private key for JWT signing (PEM format).")
    signing_algorithm: str = Field(default="RS256", description="Algorithm for signing JWT assertions.")
    lifetime_seconds: int = Field(default=300, description="Lifetime of generated JWT in seconds.")
    additional_claims: dict[str, Any] | None = Field(default=None, description="Additional claims.")

    def create_assertion_provider(self) -> Callable[[str], Awaitable[str]]:
        """Create an assertion provider callback for use with PrivateKeyJWTOAuthProvider.

        Returns:
            An async callback that takes the audience (authorization server issuer URL)
            and returns a signed JWT assertion.
        """

        async def provider(audience: str) -> str:
            now = int(time.time())
            claims: dict[str, Any] = {
                "iss": self.issuer,
                "sub": self.subject,
                "aud": audience,
                "exp": now + self.lifetime_seconds,
                "iat": now,
                "jti": str(uuid4()),
            }
            if self.additional_claims:
                claims.update(self.additional_claims)

            return jwt.encode(claims, self.signing_key, algorithm=self.signing_algorithm)

        return provider


class PrivateKeyJWTOAuthProvider(OAuthClientProvider):
    """OAuth provider for client_credentials grant with private_key_jwt authentication.

    Uses RFC 7523 Section 2.2 for client authentication via JWT assertion.

    The JWT assertion's audience MUST be the authorization server's issuer identifier
    (per RFC 7523bis security updates). The `assertion_provider` callback receives
    this audience value and must return a JWT with that audience.

    **Option 1: Pre-built JWT via Workload Identity Federation**

    In production scenarios, the JWT assertion is typically obtained from a workload
    identity provider (e.g., GCP, AWS IAM, Azure AD):

        ```python
        async def get_workload_identity_token(audience: str) -> str:
            # Fetch JWT from your identity provider
            # The JWT's audience must match the provided audience parameter
            return await fetch_token_from_identity_provider(audience=audience)

        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=get_workload_identity_token,
        )
        ```

    **Option 2: Static pre-built JWT**

    If you have a static JWT that doesn't need the audience parameter:

        ```python
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=static_assertion_provider(my_prebuilt_jwt),
        )
        ```

    **Option 3: SDK-signed JWT (for testing/simple setups)**

    For testing or simple deployments, use `SignedJWTParameters.create_assertion_provider()`:

        ```python
        jwt_params = SignedJWTParameters(
            issuer="my-client-id",
            subject="my-client-id",
            signing_key=private_key_pem,
        )
        provider = PrivateKeyJWTOAuthProvider(
            server_url="https://api.example.com",
            storage=my_token_storage,
            client_id="my-client-id",
            assertion_provider=jwt_params.create_assertion_provider(),
        )
        ```
    """

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        assertion_provider: Callable[[str], Awaitable[str]],
        scopes: str | None = None,
    ) -> None:
        """Initialize private_key_jwt OAuth provider.

        Args:
            server_url: The MCP server URL.
            storage: Token storage implementation.
            client_id: The OAuth client ID.
            assertion_provider: Async callback that takes the audience (authorization
                server's issuer identifier) and returns a JWT assertion. Use
                `SignedJWTParameters.create_assertion_provider()` for SDK-signed JWTs,
                `static_assertion_provider()` for pre-built JWTs, or provide your own
                callback for workload identity federation.
            scopes: Optional space-separated list of scopes to request.
        """
        # Build minimal client_metadata for the base class
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=["client_credentials"],
            token_endpoint_auth_method="private_key_jwt",
            scope=scopes,
        )
        super().__init__(server_url, client_metadata, storage, None, None, 300.0)
        self._assertion_provider = assertion_provider
        # Store client_info to be set during _initialize - no dynamic registration needed
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            grant_types=["client_credentials"],
            token_endpoint_auth_method="private_key_jwt",
            scope=scopes,
        )

    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    async def _perform_authorization(self) -> httpx.Request:
        """Perform client_credentials authorization with private_key_jwt."""
        return await self._exchange_token_client_credentials()

    async def _add_client_authentication_jwt(self, *, token_data: dict[str, Any]) -> None:
        """Add JWT assertion for client authentication to token endpoint parameters."""
        if not self.context.oauth_metadata:
            raise OAuthFlowError("Missing OAuth metadata for private_key_jwt flow")  # pragma: no cover

        # Audience MUST be the issuer identifier of the authorization server
        # https://datatracker.ietf.org/doc/html/draft-ietf-oauth-rfc7523bis-01
        audience = str(self.context.oauth_metadata.issuer)
        assertion = await self._assertion_provider(audience)

        # RFC 7523 Section 2.2: client authentication via JWT
        token_data["client_assertion"] = assertion
        token_data["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

    async def _exchange_token_client_credentials(self) -> httpx.Request:
        """Build token exchange request for client_credentials grant with private_key_jwt."""
        token_data: dict[str, Any] = {
            "grant_type": "client_credentials",
        }

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

        # Add JWT client authentication (RFC 7523 Section 2.2)
        await self._add_client_authentication_jwt(token_data=token_data)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx.Request("POST", token_url, data=token_data, headers=headers)


class JWTParameters(BaseModel):
    """JWT parameters."""

    assertion: str | None = Field(
        default=None,
        description="JWT assertion for JWT authentication. "
        "Will be used instead of generating a new assertion if provided.",
    )

    issuer: str | None = Field(default=None, description="Issuer for JWT assertions.")
    subject: str | None = Field(default=None, description="Subject identifier for JWT assertions.")
    audience: str | None = Field(default=None, description="Audience for JWT assertions.")
    claims: dict[str, Any] | None = Field(default=None, description="Additional claims for JWT assertions.")
    jwt_signing_algorithm: str | None = Field(default="RS256", description="Algorithm for signing JWT assertions.")
    jwt_signing_key: str | None = Field(default=None, description="Private key for JWT signing.")
    jwt_lifetime_seconds: int = Field(default=300, description="Lifetime of generated JWT in seconds.")

    def to_assertion(self, with_audience_fallback: str | None = None) -> str:
        if self.assertion is not None:
            # Prebuilt JWT (e.g. acquired out-of-band)
            assertion = self.assertion
        else:
            if not self.jwt_signing_key:
                raise OAuthFlowError("Missing signing key for JWT bearer grant")  # pragma: no cover
            if not self.issuer:
                raise OAuthFlowError("Missing issuer for JWT bearer grant")  # pragma: no cover
            if not self.subject:
                raise OAuthFlowError("Missing subject for JWT bearer grant")  # pragma: no cover

            audience = self.audience if self.audience else with_audience_fallback
            if not audience:
                raise OAuthFlowError("Missing audience for JWT bearer grant")  # pragma: no cover

            now = int(time.time())
            claims: dict[str, Any] = {
                "iss": self.issuer,
                "sub": self.subject,
                "aud": audience,
                "exp": now + self.jwt_lifetime_seconds,
                "iat": now,
                "jti": str(uuid4()),
            }
            claims.update(self.claims or {})

            assertion = jwt.encode(
                claims,
                self.jwt_signing_key,
                algorithm=self.jwt_signing_algorithm or "RS256",
            )
        return assertion


class RFC7523OAuthClientProvider(OAuthClientProvider):
    """OAuth client provider for RFC 7523 jwt-bearer grant.

    .. deprecated::
        Use :class:`ClientCredentialsOAuthProvider` for client_credentials with
        client_id + client_secret, or :class:`PrivateKeyJWTOAuthProvider` for
        client_credentials with private_key_jwt authentication instead.

    This provider supports the jwt-bearer authorization grant (RFC 7523 Section 2.1)
    where the JWT itself is the authorization grant.
    """

    def __init__(
        self,
        server_url: str,
        client_metadata: OAuthClientMetadata,
        storage: TokenStorage,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,
        jwt_parameters: JWTParameters | None = None,
    ) -> None:
        import warnings

        warnings.warn(
            "RFC7523OAuthClientProvider is deprecated. Use ClientCredentialsOAuthProvider "
            "or PrivateKeyJWTOAuthProvider instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(server_url, client_metadata, storage, redirect_handler, callback_handler, timeout)
        self.jwt_parameters = jwt_parameters

    async def _exchange_token_authorization_code(
        self, auth_code: str, code_verifier: str, *, token_data: dict[str, Any] | None = None
    ) -> httpx.Request:  # pragma: no cover
        """Build token exchange request for authorization_code flow."""
        token_data = token_data or {}
        if self.context.client_metadata.token_endpoint_auth_method == "private_key_jwt":
            self._add_client_authentication_jwt(token_data=token_data)
        return await super()._exchange_token_authorization_code(auth_code, code_verifier, token_data=token_data)

    async def _perform_authorization(self) -> httpx.Request:  # pragma: no cover
        """Perform the authorization flow."""
        if "urn:ietf:params:oauth:grant-type:jwt-bearer" in self.context.client_metadata.grant_types:
            token_request = await self._exchange_token_jwt_bearer()
            return token_request
        else:
            return await super()._perform_authorization()

    def _add_client_authentication_jwt(self, *, token_data: dict[str, Any]):  # pragma: no cover
        """Add JWT assertion for client authentication to token endpoint parameters."""
        if not self.jwt_parameters:
            raise OAuthTokenError("Missing JWT parameters for private_key_jwt flow")
        if not self.context.oauth_metadata:
            raise OAuthTokenError("Missing OAuth metadata for private_key_jwt flow")

        # We need to set the audience to the issuer identifier of the authorization server
        # https://datatracker.ietf.org/doc/html/draft-ietf-oauth-rfc7523bis-01#name-updates-to-rfc-7523
        issuer = str(self.context.oauth_metadata.issuer)
        assertion = self.jwt_parameters.to_assertion(with_audience_fallback=issuer)

        # When using private_key_jwt, in a client_credentials flow, we use RFC 7523 Section 2.2
        token_data["client_assertion"] = assertion
        token_data["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        # We need to set the audience to the resource server, the audience is difference from the one in claims
        # it represents the resource server that will validate the token
        token_data["audience"] = self.context.get_resource_url()

    async def _exchange_token_jwt_bearer(self) -> httpx.Request:
        """Build token exchange request for JWT bearer grant."""
        if not self.context.client_info:
            raise OAuthFlowError("Missing client info")  # pragma: no cover
        if not self.jwt_parameters:
            raise OAuthFlowError("Missing JWT parameters")  # pragma: no cover
        if not self.context.oauth_metadata:
            raise OAuthTokenError("Missing OAuth metadata")  # pragma: no cover

        # We need to set the audience to the issuer identifier of the authorization server
        # https://datatracker.ietf.org/doc/html/draft-ietf-oauth-rfc7523bis-01#name-updates-to-rfc-7523
        issuer = str(self.context.oauth_metadata.issuer)
        assertion = self.jwt_parameters.to_assertion(with_audience_fallback=issuer)

        token_data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }

        if self.context.should_include_resource_param(self.context.protocol_version):  # pragma: no branch
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:  # pragma: no branch
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint()
        return httpx.Request(
            "POST", token_url, data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
