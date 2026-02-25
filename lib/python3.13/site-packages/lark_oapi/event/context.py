from typing import *

from lark_oapi.core.construct import init


class EventHeader(object):
    _types = {}

    def __init__(self, d=None) -> None:
        self.event_id: Optional[str] = None
        self.token: Optional[str] = None
        self.create_time: Optional[str] = None
        self.event_type: Optional[str] = None
        self.tenant_key: Optional[str] = None
        self.app_id: Optional[str] = None
        init(self, d, self._types)


class EventContext(object):
    _types = {
        "header": EventHeader
    }

    def __init__(self, d=None) -> None:
        self.challenge: Optional[str] = None  # deprecated
        self.ts: Optional[str] = None  # p1 only
        self.uuid: Optional[str] = None  # p1 only
        self.token: Optional[str] = None  # p1 only
        self.type: Optional[str] = None  # p1 only
        self.schema: Optional[str] = None  # p2 only
        self.header: Optional[EventHeader] = None  # p2 only
        self.event: Dict = {}
        init(self, d, self._types)
