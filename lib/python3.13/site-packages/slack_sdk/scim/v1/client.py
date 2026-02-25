"""SCIM API is a set of APIs for provisioning and managing user accounts and groups.
SCIM is used by Single Sign-On (SSO) services and identity providers to manage people across a variety of tools,
including Slack.

Refer to https://docs.slack.dev/tools/python-slack-sdk/scim/ for details.
"""

import json
import logging
import urllib
from http.client import HTTPResponse
from ssl import SSLContext
from typing import Dict, Optional, Union, Any, List
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen, OpenerDirector, ProxyHandler, HTTPSHandler

from slack_sdk.errors import SlackRequestError
from .internal_utils import (
    _build_query,
    _build_request_headers,
    _debug_log_response,
    get_user_agent,
    _to_dict_without_not_given,
)
from .response import (
    SCIMResponse,
    SearchUsersResponse,
    ReadUserResponse,
    SearchGroupsResponse,
    ReadGroupResponse,
    UserCreateResponse,
    UserPatchResponse,
    UserUpdateResponse,
    UserDeleteResponse,
    GroupCreateResponse,
    GroupPatchResponse,
    GroupUpdateResponse,
    GroupDeleteResponse,
)
from .user import User
from .group import Group

from slack_sdk.http_retry import default_retry_handlers
from slack_sdk.http_retry.handler import RetryHandler
from slack_sdk.http_retry.request import HttpRequest as RetryHttpRequest
from slack_sdk.http_retry.response import HttpResponse as RetryHttpResponse
from slack_sdk.http_retry.state import RetryState

from ...proxy_env_variable_loader import load_http_proxy_from_env


class SCIMClient:
    BASE_URL = "https://api.slack.com/scim/v1/"

    token: str
    timeout: int
    ssl: Optional[SSLContext]
    proxy: Optional[str]
    base_url: str
    default_headers: Dict[str, str]
    logger: logging.Logger
    retry_handlers: List[RetryHandler]

    def __init__(
        self,
        token: str,
        timeout: int = 30,
        ssl: Optional[SSLContext] = None,
        proxy: Optional[str] = None,
        base_url: str = BASE_URL,
        default_headers: Optional[Dict[str, str]] = None,
        user_agent_prefix: Optional[str] = None,
        user_agent_suffix: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        retry_handlers: Optional[List[RetryHandler]] = None,
    ):
        """API client for SCIM API
        See https://docs.slack.dev/admins/scim-api/ for more details

        Args:
            token: An admin user's token, which starts with `xoxp-`
            timeout: Request timeout (in seconds)
            ssl: `ssl.SSLContext` to use for requests
            proxy: Proxy URL (e.g., `localhost:9000`, `http://localhost:9000`)
            base_url: The base URL for API calls
            default_headers: Request headers to add to all requests
            user_agent_prefix: Prefix for User-Agent header value
            user_agent_suffix: Suffix for User-Agent header value
            logger: Custom logger
            retry_handlers: Retry handlers
        """
        self.token = token
        self.timeout = timeout
        self.ssl = ssl
        self.proxy = proxy
        self.base_url = base_url
        self.default_headers = default_headers if default_headers else {}
        self.default_headers["User-Agent"] = get_user_agent(user_agent_prefix, user_agent_suffix)
        self.logger = logger if logger is not None else logging.getLogger(__name__)
        self.retry_handlers = retry_handlers if retry_handlers is not None else default_retry_handlers()

        if self.proxy is None or len(self.proxy.strip()) == 0:
            env_variable = load_http_proxy_from_env(self.logger)
            if env_variable is not None:
                self.proxy = env_variable

    # -------------------------
    # Users
    # -------------------------

    def search_users(
        self,
        *,
        # Pagination required as of August 30, 2019.
        count: int,
        start_index: int,
        filter: Optional[str] = None,
    ) -> SearchUsersResponse:
        return SearchUsersResponse(
            self.api_call(
                http_verb="GET",
                path="Users",
                query_params={
                    "filter": filter,
                    "count": count,
                    "startIndex": start_index,
                },
            )
        )

    def read_user(self, id: str) -> ReadUserResponse:
        return ReadUserResponse(self.api_call(http_verb="GET", path=f"Users/{quote(id)}"))

    def create_user(self, user: Union[Dict[str, Any], User]) -> UserCreateResponse:
        return UserCreateResponse(
            self.api_call(
                http_verb="POST",
                path="Users",
                body_params=user.to_dict() if isinstance(user, User) else _to_dict_without_not_given(user),
            )
        )

    def patch_user(self, id: str, partial_user: Union[Dict[str, Any], User]) -> UserPatchResponse:
        return UserPatchResponse(
            self.api_call(
                http_verb="PATCH",
                path=f"Users/{quote(id)}",
                body_params=(
                    partial_user.to_dict() if isinstance(partial_user, User) else _to_dict_without_not_given(partial_user)
                ),
            )
        )

    def update_user(self, user: Union[Dict[str, Any], User]) -> UserUpdateResponse:
        user_id = user.id if isinstance(user, User) else user["id"]
        return UserUpdateResponse(
            self.api_call(
                http_verb="PUT",
                path=f"Users/{quote(user_id)}",
                body_params=user.to_dict() if isinstance(user, User) else _to_dict_without_not_given(user),
            )
        )

    def delete_user(self, id: str) -> UserDeleteResponse:
        return UserDeleteResponse(
            self.api_call(
                http_verb="DELETE",
                path=f"Users/{quote(id)}",
            )
        )

    # -------------------------
    # Groups
    # -------------------------

    def search_groups(
        self,
        *,
        # Pagination required as of August 30, 2019.
        count: int,
        start_index: int,
        filter: Optional[str] = None,
    ) -> SearchGroupsResponse:
        return SearchGroupsResponse(
            self.api_call(
                http_verb="GET",
                path="Groups",
                query_params={
                    "filter": filter,
                    "count": count,
                    "startIndex": start_index,
                },
            )
        )

    def read_group(self, id: str) -> ReadGroupResponse:
        return ReadGroupResponse(self.api_call(http_verb="GET", path=f"Groups/{quote(id)}"))

    def create_group(self, group: Union[Dict[str, Any], Group]) -> GroupCreateResponse:
        return GroupCreateResponse(
            self.api_call(
                http_verb="POST",
                path="Groups",
                body_params=group.to_dict() if isinstance(group, Group) else _to_dict_without_not_given(group),
            )
        )

    def patch_group(self, id: str, partial_group: Union[Dict[str, Any], Group]) -> GroupPatchResponse:
        return GroupPatchResponse(
            self.api_call(
                http_verb="PATCH",
                path=f"Groups/{quote(id)}",
                body_params=(
                    partial_group.to_dict()
                    if isinstance(partial_group, Group)
                    else _to_dict_without_not_given(partial_group)
                ),
            )
        )

    def update_group(self, group: Union[Dict[str, Any], Group]) -> GroupUpdateResponse:
        group_id = group.id if isinstance(group, Group) else group["id"]
        return GroupUpdateResponse(
            self.api_call(
                http_verb="PUT",
                path=f"Groups/{quote(group_id)}",
                body_params=group.to_dict() if isinstance(group, Group) else _to_dict_without_not_given(group),
            )
        )

    def delete_group(self, id: str) -> GroupDeleteResponse:
        return GroupDeleteResponse(
            self.api_call(
                http_verb="DELETE",
                path=f"Groups/{quote(id)}",
            )
        )

    # -------------------------

    def api_call(
        self,
        *,
        http_verb: str,
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        body_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> SCIMResponse:
        """Performs a Slack API request and returns the result."""
        url = f"{self.base_url}{path}"
        query = _build_query(query_params)
        if len(query) > 0:
            url += f"?{query}"

        return self._perform_http_request(
            http_verb=http_verb,
            url=url,
            body=body_params,
            headers=_build_request_headers(
                token=self.token,
                default_headers=self.default_headers,
                additional_headers=headers,
            ),
        )

    def _perform_http_request(
        self,
        *,
        http_verb: str = "GET",
        url: str,
        body: Optional[Dict[str, Any]] = None,
        headers: Dict[str, str],
    ) -> SCIMResponse:
        if body is not None:
            if body.get("schemas") is None:
                body["schemas"] = ["urn:scim:schemas:core:1.0"]
            body = json.dumps(body)
        headers["Content-Type"] = "application/json;charset=utf-8"

        if self.logger.level <= logging.DEBUG:
            headers_for_logging = {k: "(redacted)" if k.lower() == "authorization" else v for k, v in headers.items()}
            self.logger.debug(f"Sending a request - {http_verb} url: {url}, body: {body}, headers: {headers_for_logging}")

        # NOTE: Intentionally ignore the `http_verb` here
        # Slack APIs accepts any API method requests with POST methods
        req = Request(
            method=http_verb,
            url=url,
            data=body.encode("utf-8") if body is not None else None,
            headers=headers,
        )
        resp = None
        last_error = None

        retry_state = RetryState()
        counter_for_safety = 0
        while counter_for_safety < 100:
            counter_for_safety += 1
            # If this is a retry, the next try started here. We can reset the flag.
            retry_state.next_attempt_requested = False

            try:
                resp = self._perform_http_request_internal(url, req)
                # The resp is a 200 OK response
                return resp

            except HTTPError as e:
                # read the response body here
                charset = e.headers.get_content_charset() or "utf-8"
                response_body: str = e.read().decode(charset)
                # As adding new values to HTTPError#headers can be ignored, building a new dict object here
                response_headers = dict(e.headers.items())
                resp = SCIMResponse(
                    url=url,
                    status_code=e.code,
                    raw_body=response_body,
                    headers=response_headers,
                )
                if e.code == 429:
                    # for backward-compatibility with WebClient (v.2.5.0 or older)
                    if "retry-after" not in resp.headers and "Retry-After" in resp.headers:
                        resp.headers["retry-after"] = resp.headers["Retry-After"]
                    if "Retry-After" not in resp.headers and "retry-after" in resp.headers:
                        resp.headers["Retry-After"] = resp.headers["retry-after"]
                _debug_log_response(self.logger, resp)

                # Try to find a retry handler for this error
                retry_request = RetryHttpRequest.from_urllib_http_request(req)
                retry_response = RetryHttpResponse(
                    status_code=e.code,
                    headers={k: [v] for k, v in e.headers.items()},
                    data=response_body.encode("utf-8") if response_body is not None else None,
                )
                for handler in self.retry_handlers:
                    if handler.can_retry(
                        state=retry_state,
                        request=retry_request,
                        response=retry_response,
                        error=e,
                    ):
                        if self.logger.level <= logging.DEBUG:
                            self.logger.info(
                                f"A retry handler found: {type(handler).__name__} for {req.method} {req.full_url} - {e}"
                            )
                        handler.prepare_for_next_attempt(
                            state=retry_state,
                            request=retry_request,
                            response=retry_response,
                            error=e,
                        )
                        break

                if retry_state.next_attempt_requested is False:
                    return resp

            except Exception as err:
                last_error = err
                self.logger.error(f"Failed to send a request to Slack API server: {err}")

                # Try to find a retry handler for this error
                retry_request = RetryHttpRequest.from_urllib_http_request(req)
                for handler in self.retry_handlers:
                    if handler.can_retry(
                        state=retry_state,
                        request=retry_request,
                        response=None,
                        error=err,
                    ):
                        if self.logger.level <= logging.DEBUG:
                            self.logger.info(
                                f"A retry handler found: {type(handler).__name__} for {req.method} {req.full_url} - {err}"
                            )
                        handler.prepare_for_next_attempt(
                            state=retry_state,
                            request=retry_request,
                            response=None,
                            error=err,
                        )
                        self.logger.info(f"Going to retry the same request: {req.method} {req.full_url}")
                        break

                if retry_state.next_attempt_requested is False:
                    raise err

        if resp is not None:
            return resp
        raise last_error

    def _perform_http_request_internal(self, url: str, req: Request) -> SCIMResponse:
        opener: Optional[OpenerDirector] = None
        # for security (BAN-B310)
        if url.lower().startswith("http"):
            if self.proxy is not None:
                if isinstance(self.proxy, str):
                    opener = urllib.request.build_opener(
                        ProxyHandler({"http": self.proxy, "https": self.proxy}),
                        HTTPSHandler(context=self.ssl),
                    )
                else:
                    raise SlackRequestError(f"Invalid proxy detected: {self.proxy} must be a str value")
        else:
            raise SlackRequestError(f"Invalid URL detected: {url}")

        # NOTE: BAN-B310 is already checked above
        http_resp: Optional[HTTPResponse] = None
        if opener:
            http_resp = opener.open(req, timeout=self.timeout)
        else:
            http_resp = urlopen(req, context=self.ssl, timeout=self.timeout)
        charset: str = http_resp.headers.get_content_charset() or "utf-8"
        response_body: str = http_resp.read().decode(charset)
        resp = SCIMResponse(
            url=url,
            status_code=http_resp.status,
            raw_body=response_body,
            headers=http_resp.headers,
        )
        _debug_log_response(self.logger, resp)
        return resp
