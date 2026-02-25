from typing import *

from lark_oapi.core.construct import init
from .context import EventContext
from .processor import IEventProcessor


class CustomizedEvent(EventContext):
    _types = {}

    def __init__(self, d=None):
        super().__init__(d)
        self._types.update(super()._types)
        self.event: Optional[Dict] = None
        init(self, d, self._types)


class CustomizedEventProcessor(IEventProcessor[CustomizedEvent]):
    def __init__(self, f: Callable[[CustomizedEvent], None]):
        self.f = f

    def type(self) -> Type[CustomizedEvent]:
        return CustomizedEvent

    def do(self, data: CustomizedEvent) -> None:
        self.f(data)
