from typing import Dict, Optional, List, Union, Any
from urllib.request import Request


class HttpRequest:
    """HTTP request representation"""

    method: str
    url: str
    headers: Dict[str, Union[str, List[str]]]
    body_params: Optional[Dict[str, Any]]
    data: Optional[bytes]

    def __init__(
        self,
        *,
        method: str,
        url: str,
        headers: Dict[str, Union[str, List[str]]],
        body_params: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
    ):
        self.method = method
        self.url = url
        self.headers = {k: v if isinstance(v, list) else [v] for k, v in headers.items()}
        self.body_params = body_params
        self.data = data

    @classmethod
    def from_urllib_http_request(cls, req: Request) -> "HttpRequest":
        return HttpRequest(
            method=req.method,  # type: ignore[arg-type]
            url=req.full_url,
            headers={k: v if isinstance(v, list) else [v] for k, v in req.headers.items()},
            data=req.data,  # type: ignore[arg-type]
        )
