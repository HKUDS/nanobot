from typing import Dict, Any


class WebhookResponse:
    def __init__(
        self,
        *,
        url: str,
        status_code: int,
        body: str,
        headers: Dict[str, Any],
    ):
        self.api_url = url
        self.status_code = status_code
        self.body = body
        self.headers = headers
