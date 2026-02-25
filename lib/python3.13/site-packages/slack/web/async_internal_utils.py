import asyncio
import json
from asyncio import AbstractEventLoop
from logging import Logger
from ssl import SSLContext
from typing import Union, Optional, BinaryIO, List, Dict
from urllib.parse import urljoin

import aiohttp
from aiohttp import FormData, BasicAuth, ClientSession

from slack.errors import SlackRequestError, SlackApiError
from slack.web import get_user_agent


def _get_event_loop() -> AbstractEventLoop:
    """Retrieves the event loop or creates a new one."""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _get_url(base_url: str, api_method: str) -> str:
    """Joins the base Slack URL and an API method to form an absolute URL.

    Args:
        base_url (str): The base URL
        api_method (str): The Slack Web API method. e.g. 'chat.postMessage'

    Returns:
        The absolute API URL.
            e.g. 'https://slack.com/api/chat.postMessage'
    """
    return urljoin(base_url, api_method)


def _get_headers(
    *,
    headers: dict,
    token: Optional[str],
    has_json: bool,
    has_files: bool,
    request_specific_headers: Optional[dict],
) -> Dict[str, str]:
    """Constructs the headers need for a request.
    Args:
        has_json (bool): Whether or not the request has json.
        has_files (bool): Whether or not the request has files.
        request_specific_headers (dict): Additional headers specified by the user for a specific request.

    Returns:
        The headers dictionary.
            e.g. {
                'Content-Type': 'application/json;charset=utf-8',
                'Authorization': 'Bearer xoxb-1234-1243',
                'User-Agent': 'Python/3.7.17 slack/2.1.0 Darwin/17.7.0'
            }
    """
    final_headers = {
        "User-Agent": get_user_agent(),
        "Content-Type": "application/x-www-form-urlencoded",
    }

    if token:
        final_headers.update({"Authorization": "Bearer {}".format(token)})
    if headers is None:
        headers = {}

    # Merge headers specified at client initialization.
    final_headers.update(headers)

    # Merge headers specified for a specific request. e.g. oauth.access
    if request_specific_headers:
        final_headers.update(request_specific_headers)

    if has_json:
        final_headers.update({"Content-Type": "application/json;charset=utf-8"})

    if has_files:
        # These are set automatically by the aiohttp library.
        final_headers.pop("Content-Type", None)

    return final_headers


def _build_req_args(
    *,
    token: Optional[str],
    http_verb: str,
    files: dict,
    data: Union[dict, FormData],
    params: dict,
    json: dict,  # skipcq: PYL-W0621
    headers: dict,
    auth: dict,
    ssl: Optional[SSLContext],
    proxy: Optional[str],
) -> dict:
    has_json = json is not None
    has_files = files is not None
    if has_json and http_verb != "POST":
        msg = "Json data can only be submitted as POST requests. GET requests should use the 'params' argument."
        raise SlackRequestError(msg)

    if auth:
        auth = BasicAuth(auth["client_id"], auth["client_secret"])

    if data is not None and isinstance(data, dict):
        data = {k: v for k, v in data.items() if v is not None}
    if files is not None and isinstance(files, dict):
        files = {k: v for k, v in files.items() if v is not None}
    if params is not None and isinstance(params, dict):
        params = {k: v for k, v in params.items() if v is not None}

    token: Optional[str] = token
    if params is not None and "token" in params:
        token = params.pop("token")
    if json is not None and "token" in json:
        token = json.pop("token")
    req_args = {
        "headers": _get_headers(
            headers=headers,
            token=token,
            has_json=has_json,
            has_files=has_files,
            request_specific_headers=headers,
        ),
        "data": data,
        "files": files,
        "params": params,
        "json": json,
        "ssl": ssl,
        "proxy": proxy,
        "auth": auth,
    }
    return req_args


def _files_to_data(req_args: dict) -> List[BinaryIO]:
    open_files = []
    files = req_args.pop("files", None)
    if files is not None:
        for k, v in files.items():
            if isinstance(v, str):
                f = open(v.encode("utf-8", "ignore"), "rb")
                open_files.append(f)
                req_args["data"].update({k: f})
            else:
                req_args["data"].update({k: v})
    return open_files


async def _request_with_session(
    *,
    current_session: Optional[ClientSession],
    timeout: int,
    logger: Logger,
    http_verb: str,
    api_url: str,
    req_args: dict,
) -> Dict[str, any]:
    """Submit the HTTP request with the running session or a new session.
    Returns:
        A dictionary of the response data.
    """
    session = None
    use_running_session = current_session and not current_session.closed
    if use_running_session:
        session = current_session
    else:
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            auth=req_args.pop("auth", None),
        )

    response = None
    try:
        async with session.request(http_verb, api_url, **req_args) as res:
            data = {}
            try:
                data = await res.json()
            except aiohttp.ContentTypeError:
                logger.debug(f"No response data returned from the following API call: {api_url}.")
            except json.decoder.JSONDecodeError as e:
                message = f"Failed to parse the response body: {str(e)}"
                raise SlackApiError(message, res)

            response = {
                "data": data,
                "headers": res.headers,
                "status_code": res.status,
            }
    finally:
        if not use_running_session:
            await session.close()
    return response
