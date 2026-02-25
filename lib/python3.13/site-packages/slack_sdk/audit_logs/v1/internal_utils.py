import logging
from typing import Optional, Dict, Any
from urllib.parse import quote

from slack_sdk.web.internal_utils import get_user_agent
from .response import AuditLogsResponse


def _build_query(params: Optional[Dict[str, Any]]) -> str:
    if params is not None and len(params) > 0:
        return "&".join({f"{quote(str(k))}={quote(str(v))}" for k, v in params.items() if v is not None})
    return ""


def _build_request_headers(
    token: str,
    default_headers: Dict[str, str],
    additional_headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    request_headers = {
        "Content-Type": "application/json;charset=utf-8",
        "Authorization": f"Bearer {token}",
    }
    if default_headers is None or "User-Agent" not in default_headers:
        request_headers["User-Agent"] = get_user_agent()
    if default_headers is not None:
        request_headers.update(default_headers)
    if additional_headers is not None:
        request_headers.update(additional_headers)
    return request_headers


def _debug_log_response(logger, resp: AuditLogsResponse) -> None:
    if logger.level <= logging.DEBUG:
        logger.debug(
            "Received the following response - "
            f"status: {resp.status_code}, "
            f"headers: {(dict(resp.headers))}, "
            f"body: {resp.raw_body}"
        )
