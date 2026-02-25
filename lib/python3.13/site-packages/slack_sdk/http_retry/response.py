from typing import Dict, Optional, List, Union, Any


class HttpResponse:
    """HTTP response representation"""

    status_code: int
    headers: Dict[str, Union[List[str], str]]
    body: Optional[Dict[str, Any]]
    data: Optional[bytes]

    def __init__(
        self,
        *,
        status_code: Union[int, str],
        headers: Dict[str, Union[str, List[str]]],
        body: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
    ):
        self.status_code = int(status_code)
        self.headers = {k: v if isinstance(v, list) else [v] for k, v in headers.items()}
        self.body = body
        self.data = data
