import logging
from typing import Optional, Dict, Any

from slack_sdk.web.internal_utils import (
    _parse_web_class_objects,
    get_user_agent,
)
from .webhook_response import WebhookResponse


def _build_body(original_body: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if original_body:
        body = {k: v for k, v in original_body.items() if v is not None}
        _parse_web_class_objects(body)
        return body
    return None


def _build_request_headers(
    default_headers: Dict[str, str],
    additional_headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    if default_headers is None and additional_headers is None:
        return {}

    request_headers = {
        "Content-Type": "application/json;charset=utf-8",
    }
    if default_headers is None or "User-Agent" not in default_headers:
        request_headers["User-Agent"] = get_user_agent()

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
