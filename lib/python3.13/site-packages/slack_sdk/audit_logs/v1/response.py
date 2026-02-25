import json
from typing import Dict, Any, Optional

from slack_sdk.audit_logs.v1.logs import LogsResponse


# TODO: Unlike WebClient's responses, this class has not yet provided __iter__ method
class AuditLogsResponse:
    url: str
    status_code: int
    headers: Dict[str, Any]
    raw_body: Optional[str]
    body: Optional[Dict[str, Any]]
    typed_body: Optional[LogsResponse]

    @property  # type: ignore[no-redef]
    def typed_body(self) -> Optional[LogsResponse]:
        if self.body is None:
            return None
        return LogsResponse(**self.body)

    def __init__(
        self,
        *,
        url: str,
        status_code: int,
        raw_body: Optional[str],
        headers: dict,
    ):
        self.url = url
        self.status_code = status_code
        self.headers = headers
        self.raw_body = raw_body
        self.body = json.loads(raw_body) if raw_body is not None and raw_body.startswith("{") else None
