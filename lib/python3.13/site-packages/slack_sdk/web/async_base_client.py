import logging
from ssl import SSLContext
from typing import Optional, Union, Dict, Any, List

import aiohttp
from aiohttp import FormData, BasicAuth

from .async_internal_utils import (
    _files_to_data,
    _request_with_session,
)
from .async_slack_response import AsyncSlackResponse
from .deprecation import show_deprecation_warning_if_any
from .file_upload_v2_result import FileUploadV2Result
from .internal_utils import (
    convert_bool_to_0_or_1,
    _build_req_args,
    _get_url,
    get_user_agent,
)
from ..proxy_env_variable_loader import load_http_proxy_from_env

from slack_sdk.http_retry.builtin_async_handlers import async_default_handlers
from slack_sdk.http_retry.async_handler import AsyncRetryHandler


class AsyncBaseClient:
    BASE_URL = "https://slack.com/api/"

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: int = 30,
        ssl: Optional[SSLContext] = None,
        proxy: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
        trust_env_in_session: bool = False,
        headers: Optional[dict] = None,
        user_agent_prefix: Optional[str] = None,
        user_agent_suffix: Optional[str] = None,
        # for Org-Wide App installation
        team_id: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        retry_handlers: Optional[List[AsyncRetryHandler]] = None,
    ):
        self.token = None if token is None else token.strip()
        """A string specifying an `xoxp-*` or `xoxb-*` token."""
        if not base_url.endswith("/"):
            base_url += "/"
        self.base_url = base_url
        """A string representing the Slack API base URL.
        Default is `'https://slack.com/api/'`."""
        self.timeout = timeout
        """The maximum number of seconds the client will wait
        to connect and receive a response from Slack.
        Default is 30 seconds."""
        self.ssl = ssl
        """An [`ssl.SSLContext`](https://docs.python.org/3/library/ssl.html#ssl.SSLContext)
        instance, helpful for specifying your own custom
        certificate chain."""
        self.proxy = proxy
        """String representing a fully-qualified URL to a proxy through which
        to route all requests to the Slack API. Even if this parameter
        is not specified, if any of the following environment variables are
        present, they will be loaded into this parameter: `HTTPS_PROXY`,
        `https_proxy`, `HTTP_PROXY` or `http_proxy`."""
        self.session = session
        """An [`aiohttp.ClientSession`](https://docs.aiohttp.org/en/stable/client_reference.html#client-session)
        to attach to all outgoing requests."""
        # https://github.com/slackapi/python-slack-sdk/issues/738
        self.trust_env_in_session = trust_env_in_session
        """Boolean setting whether aiohttp outgoing requests
        are allowed to read environment variables. Commonly used in conjunction
        with proxy support via the `HTTPS_PROXY`, `https_proxy`, `HTTP_PROXY` and
        `http_proxy` environment variables."""
        self.headers = headers or {}
        """`dict` representing additional request headers to attach to all requests."""
        self.headers["User-Agent"] = get_user_agent(user_agent_prefix, user_agent_suffix)
        self.default_params = {}
        if team_id is not None:
            self.default_params["team_id"] = team_id
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self.retry_handlers = retry_handlers if retry_handlers is not None else async_default_handlers()

        if self.proxy is None or len(self.proxy.strip()) == 0:
            env_variable = load_http_proxy_from_env(self._logger)
            if env_variable is not None:
                self.proxy = env_variable

    # -------------------------
    # accessors

    @property
    def logger(self) -> logging.Logger:
        """The logger this client uses."""
        return self._logger

    # -------------------------
    # api call

    async def api_call(
        self,
        api_method: str,
        *,
        http_verb: str = "POST",
        files: Optional[dict] = None,
        data: Optional[Union[dict, FormData]] = None,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
        auth: Optional[dict] = None,
    ) -> AsyncSlackResponse:
        """Create a request and execute the API call to Slack.

        Args:
            api_method (str): The target Slack API method.
                e.g. 'chat.postMessage'
            http_verb (str): HTTP Verb. e.g. 'POST'
            files (dict): Files to multipart upload.
                e.g. {image OR file: file_object OR file_path}
            data: The body to attach to the request. If a dictionary is
                provided, form-encoding will take place.
                e.g. {'key1': 'value1', 'key2': 'value2'}
            params (dict): The URL parameters to append to the URL.
                e.g. {'key1': 'value1', 'key2': 'value2'}
            json (dict): JSON for the body to attach to the request
                (if files or data is not specified).
                e.g. {'key1': 'value1', 'key2': 'value2'}
            headers (dict): Additional request headers
            auth (dict): A dictionary that consists of client_id and client_secret

        Returns:
            (AsyncSlackResponse)
                The server's response to an HTTP request. Data
                from the response can be accessed like a dict.
                If the response included 'next_cursor' it can
                be iterated on to execute subsequent requests.

        Raises:
            SlackApiError: The following Slack API call failed:
                'chat.postMessage'.
            SlackRequestError: Json data can only be submitted as
                POST requests.
        """

        api_url = _get_url(self.base_url, api_method)
        if auth is not None:
            if isinstance(auth, Dict):
                auth = BasicAuth(auth["client_id"], auth["client_secret"])  # type: ignore[assignment]
            if isinstance(auth, BasicAuth):
                if headers is None:
                    headers = {}
                headers["Authorization"] = auth.encode()
                auth = None

        headers = headers or {}
        headers.update(self.headers)
        req_args = _build_req_args(
            token=self.token,
            http_verb=http_verb,
            files=files,  # type: ignore[arg-type]
            data=data,  # type: ignore[arg-type]
            default_params=self.default_params,
            params=params,  # type: ignore[arg-type]
            json=json,  # type: ignore[arg-type]
            headers=headers,
            auth=auth,  # type: ignore[arg-type]
            ssl=self.ssl,
            proxy=self.proxy,
        )

        show_deprecation_warning_if_any(api_method)

        return await self._send(
            http_verb=http_verb,
            api_url=api_url,
            req_args=req_args,
        )

    async def _send(self, http_verb: str, api_url: str, req_args: dict) -> AsyncSlackResponse:
        """Sends the request out for transmission.

        Args:
            http_verb (str): The HTTP verb. e.g. 'GET' or 'POST'.
            api_url (str): The Slack API url. e.g. 'https://slack.com/api/chat.postMessage'
            req_args (dict): The request arguments to be attached to the request.
            e.g.
            {
                json: {
                    'attachments': [{"pretext": "pre-hello", "text": "text-world"}],
                    'channel': '#random'
                }
            }
        Returns:
            The response parsed into a AsyncSlackResponse object.
        """
        open_files = _files_to_data(req_args)
        try:
            if "params" in req_args:
                # True/False -> "1"/"0"
                req_args["params"] = convert_bool_to_0_or_1(req_args["params"])

            res = await self._request(http_verb=http_verb, api_url=api_url, req_args=req_args)
        finally:
            for f in open_files:
                f.close()

        data = {
            "client": self,
            "http_verb": http_verb,
            "api_url": api_url,
            "req_args": req_args,
        }
        return AsyncSlackResponse(**{**data, **res}).validate()

    async def _request(self, *, http_verb, api_url, req_args) -> Dict[str, Any]:
        """Submit the HTTP request with the running session or a new session.
        Returns:
            A dictionary of the response data.
        """
        return await _request_with_session(
            current_session=self.session,
            timeout=self.timeout,
            logger=self._logger,
            http_verb=http_verb,
            api_url=api_url,
            req_args=req_args,
            retry_handlers=self.retry_handlers,
        )

    async def _upload_file(
        self,
        *,
        url: str,
        data: bytes,
        logger: logging.Logger,
        timeout: int,
        proxy: Optional[str],
        ssl: Optional[SSLContext],
    ) -> FileUploadV2Result:
        """Upload a file using the issued upload URL"""
        result = await _request_with_session(
            current_session=self.session,
            timeout=timeout,
            logger=logger,
            http_verb="POST",
            api_url=url,
            req_args={"data": data, "proxy": proxy, "ssl": ssl},
            retry_handlers=self.retry_handlers,
        )
        return FileUploadV2Result(
            status=result.get("status_code"),  # type: ignore[arg-type]
            body=result.get("body"),  # type: ignore[arg-type]
        )
