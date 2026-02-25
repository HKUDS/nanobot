from typing import *

from lark_oapi.core.const import X_TT_LOGID
from lark_oapi.core.construct import init
from .raw_response import RawResponse
from .error import Error


class BaseResponse(object):
    _types = {}

    def __init__(self, d=None):
        self.raw: Optional[RawResponse] = None
        self.code: Optional[int] = None
        self.msg: Optional[str] = None
        self.error: Optional[Error] = None
        init(self, d, self._types)

    def success(self):
        return self.code is not None and self.code == 0

    def get_log_id(self) -> Optional[str]:
        if self.raw is None or self.raw.headers is None:
            return None
        return self.raw.headers.get(X_TT_LOGID)

    def get_troubleshooter(self) -> Optional[str]:
        return self.error.troubleshooter if self.error is not None else None
