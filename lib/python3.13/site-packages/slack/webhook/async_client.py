import json
import logging
from ssl import SSLContext
from typing import Dict, Union, List, Optional

import aiohttp
from aiohttp import BasicAuth, ClientSession

from slack.errors import SlackApiError
from .internal_utils import _debug_log_response, _build_request_headers, _build_body
from .webhook_response import WebhookResponse
from ..web.classes.attachments import Attachment
from ..web.classes.blocks import Block


class AsyncWebhookClient:
    logger = logging.getLogger(__name__)

    def __init__(
        self,
        url: str,
        timeout: int = 30,
        ssl: Optional[SSLContext] = None,
        proxy: Optional[str] = None,
        session: Optional[ClientSession] = None,
        trust_env_in_session: bool = False,
        auth: Optional[BasicAuth] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.url = url
        self.timeout = timeout
        self.ssl = ssl
        self.proxy = proxy
        self.trust_env_in_session = trust_env_in_session
        self.session = session
        self.auth = auth
        self.default_headers = default_headers if default_headers else {}

    async def send(
        self,
        *,
        text: Optional[str] = None,
        attachments: Optional[List[Union[Dict[str, any], Attachment]]] = None,
        blocks: Optional[List[Union[Dict[str, any], Block]]] = None,
        response_type: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookResponse:
        """Performs a Slack API request and returns the result.

        Args:
            text: The text message (even when having blocks, setting this as well is recommended as it works as fallback)
            attachments: A collection of attachments
            blocks: A collection of Block Kit UI components
            response_type: The type of message (either 'in_channel' or 'ephemeral')
            headers: Request headers to append only for this request
        Returns:
            Webhook response
        """
        return await self.send_dict(
            body={
                "text": text,
                "attachments": attachments,
                "blocks": blocks,
                "response_type": response_type,
            },
            headers=headers,
        )

    async def send_dict(self, body: Dict[str, any], headers: Optional[Dict[str, str]] = None) -> WebhookResponse:
        return await self._perform_http_request(
            body=_build_body(body),
            headers=_build_request_headers(self.default_headers, headers),
        )

    async def _perform_http_request(self, *, body: Dict[str, any], headers: Dict[str, str]) -> WebhookResponse:
        body = json.dumps(body)
        headers["Content-Type"] = "application/json;charset=utf-8"

        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"Sending a request - url: {self.url}, body: {body}, headers: {headers}")
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

        try:
            request_kwargs = {
                "headers": headers,
                "data": body,
                "ssl": self.ssl,
                "proxy": self.proxy,
            }
            async with session.request("POST", self.url, **request_kwargs) as res:
                response_body = {}
                try:
                    response_body = await res.text()
                except aiohttp.ContentTypeError:
                    self._logger.debug(f"No response data returned from the following API call: {self.url}.")
                except json.decoder.JSONDecodeError as e:
                    message = f"Failed to parse the response body: {str(e)}"
                    raise SlackApiError(message, res)

                resp = WebhookResponse(
                    url=self.url,
                    status_code=res.status,
                    body=response_body,
                    headers=res.headers,
                )
                _debug_log_response(self.logger, resp)
                return resp
        finally:
            if not use_running_session:
                await session.close()
