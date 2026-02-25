import logging
import re
from urllib.parse import urljoin, urlparse

from httpx import Request, Response
from pydantic import AnyUrl, ValidationError

from mcp.client.auth import OAuthRegistrationError, OAuthTokenError
from mcp.client.streamable_http import MCP_PROTOCOL_VERSION
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from mcp.types import LATEST_PROTOCOL_VERSION

logger = logging.getLogger(__name__)


def extract_field_from_www_auth(response: Response, field_name: str) -> str | None:
    """
    Extract field from WWW-Authenticate header.

    Returns:
        Field value if found in WWW-Authenticate header, None otherwise
    """
    www_auth_header = response.headers.get("WWW-Authenticate")
    if not www_auth_header:
        return None

    # Pattern matches: field_name="value" or field_name=value (unquoted)
    pattern = rf'{field_name}=(?:"([^"]+)"|([^\s,]+))'
    match = re.search(pattern, www_auth_header)

    if match:
        # Return quoted value if present, otherwise unquoted value
        return match.group(1) or match.group(2)

    return None


def extract_scope_from_www_auth(response: Response) -> str | None:
    """
    Extract scope parameter from WWW-Authenticate header as per RFC6750.

    Returns:
        Scope string if found in WWW-Authenticate header, None otherwise
    """
    return extract_field_from_www_auth(response, "scope")


def extract_resource_metadata_from_www_auth(response: Response) -> str | None:
    """
    Extract protected resource metadata URL from WWW-Authenticate header as per RFC9728.

    Returns:
        Resource metadata URL if found in WWW-Authenticate header, None otherwise
    """
    if not response or response.status_code != 401:
        return None  # pragma: no cover

    return extract_field_from_www_auth(response, "resource_metadata")


def build_protected_resource_metadata_discovery_urls(www_auth_url: str | None, server_url: str) -> list[str]:
    """
    Build ordered list of URLs to try for protected resource metadata discovery.

    Per SEP-985, the client MUST:
    1. Try resource_metadata from WWW-Authenticate header (if present)
    2. Fall back to path-based well-known URI: /.well-known/oauth-protected-resource/{path}
    3. Fall back to root-based well-known URI: /.well-known/oauth-protected-resource

    Args:
        www_auth_url: optional resource_metadata url extracted from the WWW-Authenticate header
        server_url: server url

    Returns:
        Ordered list of URLs to try for discovery
    """
    urls: list[str] = []

    # Priority 1: WWW-Authenticate header with resource_metadata parameter
    if www_auth_url:
        urls.append(www_auth_url)

    # Priority 2-3: Well-known URIs (RFC 9728)
    parsed = urlparse(server_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Priority 2: Path-based well-known URI (if server has a path component)
    if parsed.path and parsed.path != "/":
        path_based_url = urljoin(base_url, f"/.well-known/oauth-protected-resource{parsed.path}")
        urls.append(path_based_url)

    # Priority 3: Root-based well-known URI
    root_based_url = urljoin(base_url, "/.well-known/oauth-protected-resource")
    urls.append(root_based_url)

    return urls


def get_client_metadata_scopes(
    www_authenticate_scope: str | None,
    protected_resource_metadata: ProtectedResourceMetadata | None,
    authorization_server_metadata: OAuthMetadata | None = None,
) -> str | None:
    """Select scopes as outlined in the 'Scope Selection Strategy' in the MCP spec."""
    # Per MCP spec, scope selection priority order:
    # 1. Use scope from WWW-Authenticate header (if provided)
    # 2. Use all scopes from PRM scopes_supported (if available)
    # 3. Omit scope parameter if neither is available

    if www_authenticate_scope is not None:
        # Priority 1: WWW-Authenticate header scope
        return www_authenticate_scope
    elif protected_resource_metadata is not None and protected_resource_metadata.scopes_supported is not None:
        # Priority 2: PRM scopes_supported
        return " ".join(protected_resource_metadata.scopes_supported)
    elif authorization_server_metadata is not None and authorization_server_metadata.scopes_supported is not None:
        return " ".join(authorization_server_metadata.scopes_supported)  # pragma: no cover
    else:
        # Priority 3: Omit scope parameter
        return None


def build_oauth_authorization_server_metadata_discovery_urls(auth_server_url: str | None, server_url: str) -> list[str]:
    """
    Generate ordered list of (url, type) tuples for discovery attempts.

    Args:
        auth_server_url: URL for the OAuth Authorization Metadata URL if found, otherwise None
        server_url: URL for the MCP server, used as a fallback if auth_server_url is None
    """

    if not auth_server_url:
        # Legacy path using the 2025-03-26 spec:
        # link: https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization
        parsed = urlparse(server_url)
        return [f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"]

    urls: list[str] = []
    parsed = urlparse(auth_server_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # RFC 8414: Path-aware OAuth discovery
    if parsed.path and parsed.path != "/":
        oauth_path = f"/.well-known/oauth-authorization-server{parsed.path.rstrip('/')}"
        urls.append(urljoin(base_url, oauth_path))

        # RFC 8414 section 5: Path-aware OIDC discovery
        # See https://www.rfc-editor.org/rfc/rfc8414.html#section-5
        oidc_path = f"/.well-known/openid-configuration{parsed.path.rstrip('/')}"
        urls.append(urljoin(base_url, oidc_path))

        # https://openid.net/specs/openid-connect-discovery-1_0.html
        oidc_path = f"{parsed.path.rstrip('/')}/.well-known/openid-configuration"
        urls.append(urljoin(base_url, oidc_path))
        return urls

    # OAuth root
    urls.append(urljoin(base_url, "/.well-known/oauth-authorization-server"))

    # OIDC 1.0 fallback (appends to full URL per OIDC spec)
    # https://openid.net/specs/openid-connect-discovery-1_0.html
    urls.append(urljoin(base_url, "/.well-known/openid-configuration"))

    return urls


async def handle_protected_resource_response(
    response: Response,
) -> ProtectedResourceMetadata | None:
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
            return metadata

        except ValidationError:  # pragma: no cover
            # Invalid metadata - try next URL
            return None
    else:
        # Not found - try next URL in fallback chain
        return None


async def handle_auth_metadata_response(response: Response) -> tuple[bool, OAuthMetadata | None]:
    if response.status_code == 200:
        try:
            content = await response.aread()
            asm = OAuthMetadata.model_validate_json(content)
            return True, asm
        except ValidationError:  # pragma: no cover
            return True, None
    elif response.status_code < 400 or response.status_code >= 500:
        return False, None  # Non-4XX error, stop trying
    return True, None


def create_oauth_metadata_request(url: str) -> Request:
    return Request("GET", url, headers={MCP_PROTOCOL_VERSION: LATEST_PROTOCOL_VERSION})


def create_client_registration_request(
    auth_server_metadata: OAuthMetadata | None, client_metadata: OAuthClientMetadata, auth_base_url: str
) -> Request:
    """Build registration request or skip if already registered."""

    if auth_server_metadata and auth_server_metadata.registration_endpoint:
        registration_url = str(auth_server_metadata.registration_endpoint)
    else:
        registration_url = urljoin(auth_base_url, "/register")

    registration_data = client_metadata.model_dump(by_alias=True, mode="json", exclude_none=True)

    return Request("POST", registration_url, json=registration_data, headers={"Content-Type": "application/json"})


async def handle_registration_response(response: Response) -> OAuthClientInformationFull:
    """Handle registration response."""
    if response.status_code not in (200, 201):
        await response.aread()
        raise OAuthRegistrationError(f"Registration failed: {response.status_code} {response.text}")

    try:
        content = await response.aread()
        client_info = OAuthClientInformationFull.model_validate_json(content)
        return client_info
        # self.context.client_info = client_info
        # await self.context.storage.set_client_info(client_info)
    except ValidationError as e:  # pragma: no cover
        raise OAuthRegistrationError(f"Invalid registration response: {e}")


def is_valid_client_metadata_url(url: str | None) -> bool:
    """Validate that a URL is suitable for use as a client_id (CIMD).

    The URL must be HTTPS with a non-root pathname.

    Args:
        url: The URL to validate

    Returns:
        True if the URL is a valid HTTPS URL with a non-root pathname
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.path not in ("", "/")
    except Exception:
        return False


def should_use_client_metadata_url(
    oauth_metadata: OAuthMetadata | None,
    client_metadata_url: str | None,
) -> bool:
    """Determine if URL-based client ID (CIMD) should be used instead of DCR.

    URL-based client IDs should be used when:
    1. The server advertises client_id_metadata_document_supported=true
    2. The client has a valid client_metadata_url configured

    Args:
        oauth_metadata: OAuth authorization server metadata
        client_metadata_url: URL-based client ID (already validated)

    Returns:
        True if CIMD should be used, False if DCR should be used
    """
    if not client_metadata_url:
        return False

    if not oauth_metadata:
        return False

    return oauth_metadata.client_id_metadata_document_supported is True


def create_client_info_from_metadata_url(
    client_metadata_url: str, redirect_uris: list[AnyUrl] | None = None
) -> OAuthClientInformationFull:
    """Create client information using a URL-based client ID (CIMD).

    When using URL-based client IDs, the URL itself becomes the client_id
    and no client_secret is used (token_endpoint_auth_method="none").

    Args:
        client_metadata_url: The URL to use as the client_id
        redirect_uris: The redirect URIs from the client metadata (passed through for
            compatibility with OAuthClientInformationFull which inherits from OAuthClientMetadata)

    Returns:
        OAuthClientInformationFull with the URL as client_id
    """
    return OAuthClientInformationFull(
        client_id=client_metadata_url,
        token_endpoint_auth_method="none",
        redirect_uris=redirect_uris,
    )


async def handle_token_response_scopes(
    response: Response,
) -> OAuthToken:
    """Parse and validate token response with optional scope validation.

    Parses token response JSON. Callers should check response.status_code before calling.

    Args:
        response: HTTP response from token endpoint (status already checked by caller)

    Returns:
        Validated OAuthToken model

    Raises:
        OAuthTokenError: If response JSON is invalid
    """
    try:
        content = await response.aread()
        token_response = OAuthToken.model_validate_json(content)
        return token_response
    except ValidationError as e:  # pragma: no cover
        raise OAuthTokenError(f"Invalid token response: {e}")
