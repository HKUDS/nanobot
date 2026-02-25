from typing import Optional, Dict

from lark_oapi.core.const import CONTENT_TYPE


class RawResponse(object):

    def __init__(self):
        self.status_code: Optional[int] = None
        self.headers: Dict[str, str] = {}
        self.content: Optional[bytes] = None

    def set_content_type(self, content_type: str) -> None:
        self.headers[CONTENT_TYPE] = content_type
