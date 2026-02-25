import json
import logging
import urllib
from http.client import HTTPResponse
from ssl import SSLContext
from typing import Dict, Union, List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen, OpenerDirector, ProxyHandler, HTTPSHandler

from slack.errors import SlackRequestError
from .internal_utils import _build_body, _build_request_headers, _debug_log_response
from .webhook_response import WebhookResponse
from ..web.classes.attachments import Attachment
from ..web.classes.blocks import Block


class WebhookClient:
    logger = logging.getLogger(__name__)

    def __init__(
        self,
        url: str,
        timeout: int = 30,
        ssl: Optional[SSLContext] = None,
        proxy: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.url = url
        self.timeout = timeout
        self.ssl = ssl
        self.proxy = proxy
        self.default_headers = default_headers if default_headers else {}

    def send(
        self,
        *,
        text: Optional[str] = None,
        attachments: Optional[List[Union[Dict[str, any], Attachment]]] = None,
        blocks: Optional[List[Union[Dict[str, any], Block]]] = None,
        response_type: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookResponse:
        return self.send_dict(
            body={
                "text": text,
                "attachments": attachments,
                "blocks": blocks,
                "response_type": response_type,
            },
            headers=headers,
        )

    def send_dict(self, body: Dict[str, any], headers: Optional[Dict[str, str]] = None) -> WebhookResponse:
        return self._perform_http_request(
            body=_build_body(body),
            headers=_build_request_headers(self.default_headers, headers),
        )

    def _perform_http_request(self, *, body: Dict[str, any], headers: Dict[str, str]) -> WebhookResponse:
        body = json.dumps(body)
        headers["Content-Type"] = "application/json;charset=utf-8"

        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"Sending a request - url: {self.url}, body: {body}, headers: {headers}")
        try:
            url = self.url
            opener: Optional[OpenerDirector] = None
            # for security (BAN-B310)
            if url.lower().startswith("http"):
                req = Request(method="POST", url=url, data=body.encode("utf-8"), headers=headers)
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
            resp: Optional[HTTPResponse] = None
            if opener:
                resp = opener.open(req, timeout=self.timeout)  # skipcq: BAN-B310
            else:
                resp = urlopen(req, context=self.ssl, timeout=self.timeout)  # skipcq: BAN-B310
            charset: str = resp.headers.get_content_charset() or "utf-8"
            response_body: str = resp.read().decode(charset)
            resp = WebhookResponse(
                url=url,
                status_code=resp.status,
                body=response_body,
                headers=resp.headers,
            )
            _debug_log_response(self.logger, resp)
            return resp

        except HTTPError as e:
            charset = e.headers.get_content_charset() or "utf-8"
            body: str = e.read().decode(charset)  # read the response body here
            resp = WebhookResponse(
                url=url,
                status_code=e.code,
                body=body,
                headers=e.headers,
            )
            if e.code == 429:
                # for backward-compatibility with WebClient (v.2.5.0 or older)
                resp.headers["Retry-After"] = resp.headers["retry-after"]
            _debug_log_response(self.logger, resp)
            return resp

        except Exception as err:
            self.logger.error(f"Failed to send a request to Slack API server: {err}")
            raise err
