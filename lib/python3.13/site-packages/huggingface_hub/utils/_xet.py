import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

from .. import constants
from . import hf_raise_for_status, http_backoff, validate_hf_hub_args


XET_CONNECTION_INFO_SAFETY_PERIOD = 60  # seconds
XET_CONNECTION_INFO_CACHE_SIZE = 1_000
XET_CONNECTION_INFO_CACHE: dict[str, "XetConnectionInfo"] = {}


class XetTokenType(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class XetFileData:
    file_hash: str
    refresh_route: str


@dataclass(frozen=True)
class XetConnectionInfo:
    access_token: str
    expiration_unix_epoch: int
    endpoint: str


def parse_xet_file_data_from_response(
    response: httpx.Response, endpoint: Optional[str] = None
) -> Optional[XetFileData]:
    """
    Parse XET file metadata from an HTTP response.

    This function extracts XET file metadata from the HTTP headers or HTTP links
    of a given response object. If the required metadata is not found, it returns `None`.

    Args:
        response (`httpx.Response`):
            The HTTP response object containing headers dict and links dict to extract the XET metadata from.
    Returns:
        `Optional[XetFileData]`:
            An instance of `XetFileData` containing the file hash and refresh route if the metadata
            is found. Returns `None` if the required metadata is missing.
    """
    if response is None:
        return None
    try:
        file_hash = response.headers[constants.HUGGINGFACE_HEADER_X_XET_HASH]

        if constants.HUGGINGFACE_HEADER_LINK_XET_AUTH_KEY in response.links:
            refresh_route = response.links[constants.HUGGINGFACE_HEADER_LINK_XET_AUTH_KEY]["url"]
        else:
            refresh_route = response.headers[constants.HUGGINGFACE_HEADER_X_XET_REFRESH_ROUTE]
    except KeyError:
        return None
    endpoint = endpoint if endpoint is not None else constants.ENDPOINT
    if refresh_route.startswith(constants.HUGGINGFACE_CO_URL_HOME):
        refresh_route = refresh_route.replace(constants.HUGGINGFACE_CO_URL_HOME.rstrip("/"), endpoint.rstrip("/"))
    return XetFileData(
        file_hash=file_hash,
        refresh_route=refresh_route,
    )


def parse_xet_connection_info_from_headers(headers: dict[str, str]) -> Optional[XetConnectionInfo]:
    """
    Parse XET connection info from the HTTP headers or return None if not found.
    Args:
        headers (`dict`):
           HTTP headers to extract the XET metadata from.
    Returns:
        `XetConnectionInfo` or `None`:
            The information needed to connect to the XET storage service.
            Returns `None` if the headers do not contain the XET connection info.
    """
    try:
        endpoint = headers[constants.HUGGINGFACE_HEADER_X_XET_ENDPOINT]
        access_token = headers[constants.HUGGINGFACE_HEADER_X_XET_ACCESS_TOKEN]
        expiration_unix_epoch = int(headers[constants.HUGGINGFACE_HEADER_X_XET_EXPIRATION])
    except (KeyError, ValueError, TypeError):
        return None

    return XetConnectionInfo(
        endpoint=endpoint,
        access_token=access_token,
        expiration_unix_epoch=expiration_unix_epoch,
    )


@validate_hf_hub_args
def refresh_xet_connection_info(
    *,
    file_data: XetFileData,
    headers: dict[str, str],
) -> XetConnectionInfo:
    """
    Utilizes the information in the parsed metadata to request the Hub xet connection information.
    This includes the access token, expiration, and XET service URL.
    Args:
        file_data: (`XetFileData`):
            The file data needed to refresh the xet connection information.
        headers (`dict[str, str]`):
            Headers to use for the request, including authorization headers and user agent.
    Returns:
        `XetConnectionInfo`:
            The connection information needed to make the request to the xet storage service.
    Raises:
        [`~utils.HfHubHTTPError`]
            If the Hub API returned an error.
        [`ValueError`](https://docs.python.org/3/library/exceptions.html#ValueError)
            If the Hub API response is improperly formatted.
    """
    if file_data.refresh_route is None:
        raise ValueError("The provided xet metadata does not contain a refresh endpoint.")
    return _fetch_xet_connection_info_with_url(file_data.refresh_route, headers)


@validate_hf_hub_args
def fetch_xet_connection_info_from_repo_info(
    *,
    token_type: XetTokenType,
    repo_id: str,
    repo_type: str,
    revision: Optional[str] = None,
    headers: dict[str, str],
    endpoint: Optional[str] = None,
    params: Optional[dict[str, str]] = None,
) -> XetConnectionInfo:
    """
    Uses the repo info to request a xet access token from Hub.
    Args:
        token_type (`XetTokenType`):
            Type of the token to request: `"read"` or `"write"`.
        repo_id (`str`):
            A namespace (user or an organization) and a repo name separated by a `/`.
        repo_type (`str`):
            Type of the repo to upload to: `"model"`, `"dataset"` or `"space"`.
        revision (`str`, `optional`):
            The revision of the repo to get the token for.
        headers (`dict[str, str]`):
            Headers to use for the request, including authorization headers and user agent.
        endpoint (`str`, `optional`):
            The endpoint to use for the request. Defaults to the Hub endpoint.
        params (`dict[str, str]`, `optional`):
            Additional parameters to pass with the request.
    Returns:
        `XetConnectionInfo`:
            The connection information needed to make the request to the xet storage service.
    Raises:
        [`~utils.HfHubHTTPError`]
            If the Hub API returned an error.
        [`ValueError`](https://docs.python.org/3/library/exceptions.html#ValueError)
            If the Hub API response is improperly formatted.
    """
    endpoint = endpoint if endpoint is not None else constants.ENDPOINT
    url = f"{endpoint}/api/{repo_type}s/{repo_id}/xet-{token_type.value}-token/{revision}"
    return _fetch_xet_connection_info_with_url(url, headers, params)


@validate_hf_hub_args
def _fetch_xet_connection_info_with_url(
    url: str,
    headers: dict[str, str],
    params: Optional[dict[str, str]] = None,
) -> XetConnectionInfo:
    """
    Requests the xet connection info from the supplied URL. This includes the
    access token, expiration time, and endpoint to use for the xet storage service.

    Result is cached to avoid redundant requests.

    Args:
        url: (`str`):
            The access token endpoint URL.
        headers (`dict[str, str]`):
            Headers to use for the request, including authorization headers and user agent.
        params (`dict[str, str]`, `optional`):
            Additional parameters to pass with the request.
    Returns:
        `XetConnectionInfo`:
            The connection information needed to make the request to the xet storage service.
    Raises:
        [`~utils.HfHubHTTPError`]
            If the Hub API returned an error.
        [`ValueError`](https://docs.python.org/3/library/exceptions.html#ValueError)
            If the Hub API response is improperly formatted.
    """
    # Check cache first
    cache_key = _cache_key(url, headers, params)
    cached_info = XET_CONNECTION_INFO_CACHE.get(cache_key)
    if cached_info is not None:
        if not _is_expired(cached_info):
            return cached_info

    # Fetch from server
    resp = http_backoff("GET", url, headers=headers, params=params)
    hf_raise_for_status(resp)

    metadata = parse_xet_connection_info_from_headers(resp.headers)  # type: ignore
    if metadata is None:
        raise ValueError("Xet headers have not been correctly set by the server.")

    # Delete expired cache entries
    for k, v in list(XET_CONNECTION_INFO_CACHE.items()):
        if _is_expired(v):
            XET_CONNECTION_INFO_CACHE.pop(k, None)

    # Enforce cache size limit
    if len(XET_CONNECTION_INFO_CACHE) >= XET_CONNECTION_INFO_CACHE_SIZE:
        XET_CONNECTION_INFO_CACHE.pop(next(iter(XET_CONNECTION_INFO_CACHE)))

    # Update cache
    XET_CONNECTION_INFO_CACHE[cache_key] = metadata

    return metadata


def _cache_key(url: str, headers: dict[str, str], params: Optional[dict[str, str]]) -> str:
    """Return a unique cache key for the given request parameters."""
    lower_headers = {k.lower(): v for k, v in headers.items()}  # casing is not guaranteed here
    auth_header = lower_headers.get("authorization", "")
    params_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items(), key=lambda x: x[0]))
    return f"{url}|{auth_header}|{params_str}"


def _is_expired(connection_info: XetConnectionInfo) -> bool:
    """Check if the given XET connection info is expired."""
    return connection_info.expiration_unix_epoch <= int(time.time()) + XET_CONNECTION_INFO_SAFETY_PERIOD
