import logging
from ssl import SSLContext
from typing import Optional, Union, Dict

import aiohttp
from aiohttp import FormData

from slack.web import convert_bool_to_0_or_1, get_user_agent
from slack.web.async_internal_utils import (
    _build_req_args,
    _get_url,
    _files_to_data,
    _request_with_session,
)
from slack.web.async_slack_response import AsyncSlackResponse
from slack.web.deprecation import show_2020_01_deprecation


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
    ):
        self.token = None if token is None else token.strip()
        self.base_url = base_url
        self.timeout = timeout
        self.ssl = ssl
        self.proxy = proxy
        self.session = session
        # https://github.com/slackapi/python-slack-sdk/issues/738
        self.trust_env_in_session = trust_env_in_session
        self.headers = headers or {}
        self.headers["User-Agent"] = get_user_agent(user_agent_prefix, user_agent_suffix)
        self._logger = logging.getLogger(__name__)

    async def api_call(  # skipcq: PYL-R1710
        self,
        api_method: str,
        *,
        http_verb: str = "POST",
        files: dict = None,
        data: Union[dict, FormData] = None,
        params: dict = None,
        json: dict = None,  # skipcq: PYL-W0621
        headers: dict = None,
        auth: dict = None,
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
        headers = headers or {}
        headers.update(self.headers)

        req_args = _build_req_args(
            token=self.token,
            http_verb=http_verb,
            files=files,
            data=data,
            params=params,
            json=json,  # skipcq: PYL-W0621
            headers=headers,
            auth=auth,
            ssl=self.ssl,
            proxy=self.proxy,
        )

        show_2020_01_deprecation(api_method)

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

    async def _request(self, *, http_verb, api_url, req_args) -> Dict[str, any]:
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
        )
