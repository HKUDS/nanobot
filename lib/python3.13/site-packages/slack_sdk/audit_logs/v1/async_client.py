"""Audit Logs API is a set of APIs for monitoring what’s happening in your Enterprise Grid organization.

Refer to https://docs.slack.dev/tools/python-slack-sdk/audit-logs for details.
"""

import json
import logging
from ssl import SSLContext
from typing import Any, List
from typing import Dict, Optional

import aiohttp
from aiohttp import BasicAuth, ClientSession

from slack_sdk.errors import SlackApiError
from .internal_utils import (
    _build_request_headers,
    _debug_log_response,
    get_user_agent,
)
from .response import AuditLogsResponse
from slack_sdk.http_retry.async_handler import AsyncRetryHandler
from slack_sdk.http_retry.builtin_async_handlers import async_default_handlers
from slack_sdk.http_retry.request import HttpRequest as RetryHttpRequest
from slack_sdk.http_retry.response import HttpResponse as RetryHttpResponse
from slack_sdk.http_retry.state import RetryState
from ...proxy_env_variable_loader import load_http_proxy_from_env


class AsyncAuditLogsClient:
    BASE_URL = "https://api.slack.com/audit/v1/"

    token: str
    timeout: int
    ssl: Optional[SSLContext]
    proxy: Optional[str]
    base_url: str
    session: Optional[ClientSession]
    trust_env_in_session: bool
    auth: Optional[BasicAuth]
    default_headers: Dict[str, str]
    logger: logging.Logger
    retry_handlers: List[AsyncRetryHandler]

    def __init__(
        self,
        token: str,
        timeout: int = 30,
        ssl: Optional[SSLContext] = None,
        proxy: Optional[str] = None,
        base_url: str = BASE_URL,
        session: Optional[ClientSession] = None,
        trust_env_in_session: bool = False,
        auth: Optional[BasicAuth] = None,
        default_headers: Optional[Dict[str, str]] = None,
        user_agent_prefix: Optional[str] = None,
        user_agent_suffix: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        retry_handlers: Optional[List[AsyncRetryHandler]] = None,
    ):
        """API client for Audit Logs API
        See https://docs.slack.dev/admins/audit-logs-api/ for more details

        Args:
            token: An admin user's token, which starts with `xoxp-`
            timeout: Request timeout (in seconds)
            ssl: `ssl.SSLContext` to use for requests
            proxy: Proxy URL (e.g., `localhost:9000`, `http://localhost:9000`)
            base_url: The base URL for API calls
            session: `aiohttp.ClientSession` instance
            trust_env_in_session: True/False for `aiohttp.ClientSession`
            auth: Basic auth info for `aiohttp.ClientSession`
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
        self.session = session
        self.trust_env_in_session = trust_env_in_session
        self.auth = auth
        self.default_headers = default_headers if default_headers else {}
        self.default_headers["User-Agent"] = get_user_agent(user_agent_prefix, user_agent_suffix)
        self.logger = logger if logger is not None else logging.getLogger(__name__)
        self.retry_handlers = retry_handlers if retry_handlers is not None else async_default_handlers()

        if self.proxy is None or len(self.proxy.strip()) == 0:
            env_variable = load_http_proxy_from_env(self.logger)
            if env_variable is not None:
                self.proxy = env_variable

    async def schemas(
        self,
        *,
        query_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> AuditLogsResponse:
        """Returns information about the kind of objects which the Audit Logs API
        returns as a list of all objects and a short description.
        Authentication not required.

        Args:
            query_params: Set any values if you want to add query params
            headers: Additional request headers
        Returns:
            API response
        """
        return await self.api_call(
            path="schemas",
            query_params=query_params,
            headers=headers,
        )

    async def actions(
        self,
        *,
        query_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> AuditLogsResponse:
        """Returns information about the kind of actions that the Audit Logs API
        returns as a list of all actions and a short description of each.
        Authentication not required.

        Args:
            query_params: Set any values if you want to add query params
            headers: Additional request headers

        Returns:
            API response
        """
        return await self.api_call(
            path="actions",
            query_params=query_params,
            headers=headers,
        )

    async def logs(
        self,
        *,
        latest: Optional[int] = None,
        oldest: Optional[int] = None,
        limit: Optional[int] = None,
        action: Optional[str] = None,
        actor: Optional[str] = None,
        entity: Optional[str] = None,
        cursor: Optional[str] = None,
        additional_query_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> AuditLogsResponse:
        """This is the primary endpoint for retrieving actual audit events from your organization.
        It will return a list of actions that have occurred on the installed workspace or grid organization.
        Authentication required.

        The following filters can be applied in order to narrow the range of actions returned.
        Filters are added as query string parameters and can be combined together.
        Multiple filter parameters are additive (a boolean AND) and are separated
        with an ampersand (&) in the query string. Filtering is entirely optional.

        Args:
            latest: Unix timestamp of the most recent audit event to include (inclusive).
            oldest: Unix timestamp of the least recent audit event to include (inclusive).
                Data is not available prior to March 2018.
            limit: Number of results to optimistically return, maximum 9999.
            action: Name of the action.
            actor: User ID who initiated the action.
            entity: ID of the target entity of the action (such as a channel, workspace, organization, file).
            cursor: The next page cursor of pagination
            additional_query_params: Add anything else if you need to use the ones this library does not support
            headers: Additional request headers

        Returns:
            API response
        """
        query_params = {
            "latest": latest,
            "oldest": oldest,
            "limit": limit,
            "action": action,
            "actor": actor,
            "entity": entity,
            "cursor": cursor,
        }
        if additional_query_params is not None:
            query_params.update(additional_query_params)
        query_params = {k: v for k, v in query_params.items() if v is not None}
        return await self.api_call(
            path="logs",
            query_params=query_params,
            headers=headers,
        )

    async def api_call(
        self,
        *,
        http_verb: str = "GET",
        path: str,
        query_params: Optional[Dict[str, Any]] = None,
        body_params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> AuditLogsResponse:
        url = f"{self.base_url}{path}"
        return await self._perform_http_request(
            http_verb=http_verb,
            url=url,
            query_params=query_params,
            body_params=body_params,
            headers=_build_request_headers(
                token=self.token,
                default_headers=self.default_headers,
                additional_headers=headers,
            ),
        )

    async def _perform_http_request(
        self,
        *,
        http_verb: str,
        url: str,
        query_params: Optional[Dict[str, Any]],
        body_params: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ) -> AuditLogsResponse:
        if body_params is not None:
            body_params = json.dumps(body_params)  # type: ignore[assignment]
        headers["Content-Type"] = "application/json;charset=utf-8"

        session: Optional[ClientSession] = None
        use_running_session = self.session and not self.session.closed
        if use_running_session:
            session = self.session
        else:
            session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                auth=self.auth,
                trust_env=self.trust_env_in_session,
            )

        last_error = None
        resp: Optional[AuditLogsResponse] = None
        try:
            request_kwargs = {
                "headers": headers,
                "params": query_params,
                "data": body_params,
                "ssl": self.ssl,
                "proxy": self.proxy,
            }
            retry_request = RetryHttpRequest(
                method=http_verb,
                url=url,
                headers=headers,  # type: ignore[arg-type]
                body_params=body_params,
            )

            retry_state = RetryState()
            counter_for_safety = 0
            while counter_for_safety < 100:
                counter_for_safety += 1
                # If this is a retry, the next try started here. We can reset the flag.
                retry_state.next_attempt_requested = False
                retry_response: Optional[RetryHttpResponse] = None
                response_body = ""

                if self.logger.level <= logging.DEBUG:
                    headers_for_logging = {
                        k: "(redacted)" if k.lower() == "authorization" else v for k, v in headers.items()
                    }
                    self.logger.debug(
                        f"Sending a request - "
                        f"url: {url}, "
                        f"params: {query_params}, "
                        f"body: {body_params}, "
                        f"headers: {headers_for_logging}"
                    )

                try:
                    async with session.request(http_verb, url, **request_kwargs) as res:  # type: ignore[arg-type, union-attr] # noqa: E501
                        try:
                            response_body = await res.text()
                            retry_response = RetryHttpResponse(
                                status_code=res.status,
                                headers=res.headers,  # type: ignore[arg-type]
                                data=response_body.encode("utf-8") if response_body is not None else None,
                            )
                        except aiohttp.ContentTypeError:
                            self.logger.debug(f"No response data returned from the following API call: {url}.")
                            retry_response = RetryHttpResponse(
                                status_code=res.status,
                                headers=res.headers,  # type: ignore[arg-type]
                            )
                        except json.decoder.JSONDecodeError as e:
                            message = f"Failed to parse the response body: {str(e)}"
                            raise SlackApiError(message, res)

                        if res.status == 429:
                            for handler in self.retry_handlers:
                                if await handler.can_retry_async(
                                    state=retry_state,
                                    request=retry_request,
                                    response=retry_response,
                                ):
                                    if self.logger.level <= logging.DEBUG:
                                        self.logger.info(
                                            f"A retry handler found: {type(handler).__name__} "
                                            f"for {http_verb} {url} - rate_limited"
                                        )
                                    await handler.prepare_for_next_attempt_async(
                                        state=retry_state,
                                        request=retry_request,
                                        response=retry_response,
                                    )
                                    break

                        if retry_state.next_attempt_requested is False:
                            resp = AuditLogsResponse(
                                url=url,
                                status_code=res.status,
                                raw_body=response_body,
                                headers=res.headers,  # type: ignore[arg-type]
                            )
                            _debug_log_response(self.logger, resp)
                            return resp

                except Exception as e:
                    last_error = e
                    for handler in self.retry_handlers:
                        if await handler.can_retry_async(
                            state=retry_state,
                            request=retry_request,
                            response=retry_response,
                            error=e,
                        ):
                            if self.logger.level <= logging.DEBUG:
                                self.logger.info(
                                    f"A retry handler found: {type(handler).__name__} " f"for {http_verb} {url} - {e}"
                                )
                            await handler.prepare_for_next_attempt_async(
                                state=retry_state,
                                request=retry_request,
                                response=retry_response,
                                error=e,
                            )
                            break

                    if retry_state.next_attempt_requested is False:
                        raise last_error

            if resp is not None:
                return resp
            raise last_error  # type: ignore[misc]

        finally:
            if not use_running_session:
                await session.close()  # type: ignore[union-attr]

        return resp
