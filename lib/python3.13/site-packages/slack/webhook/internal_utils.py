import logging
from typing import Optional, Dict

from slack.web import get_user_agent, convert_bool_to_0_or_1
from slack.web.internal_utils import _parse_web_class_objects
from slack.webhook import WebhookResponse


def _build_body(original_body: Dict[str, any]) -> Dict[str, any]:
    body = {k: v for k, v in original_body.items() if v is not None}
    body = convert_bool_to_0_or_1(body)
    _parse_web_class_objects(body)
    return body


def _build_request_headers(
    default_headers: Dict[str, str],
    additional_headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    if additional_headers is None:
        return {}

    request_headers = {
        "User-Agent": get_user_agent(),
        "Content-Type": "application/json;charset=utf-8",
    }
    request_headers.update(default_headers)
    if additional_headers:
        request_headers.update(additional_headers)
    return request_headers


def _debug_log_response(logger, resp: WebhookResponse) -> None:
    if logger.level <= logging.DEBUG:
        logger.debug(
            "Received the following response - "
            f"status: {resp.status_code}, "
            f"headers: {(dict(resp.headers))}, "
            f"body: {resp.body}"
        )
