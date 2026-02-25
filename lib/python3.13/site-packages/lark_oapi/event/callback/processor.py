from typing import Any, Optional, Union, Dict, List, Set, IO, Callable, Type

from lark_oapi.event.processor import ICallBackProcessor
from .model.p2_card_action_trigger import P2CardActionTrigger, P2CardActionTriggerResponse
from .model.p2_url_preview_get import P2URLPreviewGet, P2URLPreviewGetResponse


class P2CardActionTriggerProcessor(ICallBackProcessor[P2CardActionTrigger]):
    def __init__(self, f: Callable[[P2CardActionTrigger], P2CardActionTriggerResponse]):
        self.f = f

    def type(self) -> Type[P2CardActionTrigger]:
        return P2CardActionTrigger

    def do(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        return self.f(data)


class P2URLPreviewGetProcessor(ICallBackProcessor[P2URLPreviewGet]):
    def __init__(self, f: Callable[[P2URLPreviewGet], P2URLPreviewGetResponse]):
        self.f = f

    def type(self) -> Type[P2URLPreviewGet]:
        return P2URLPreviewGet

    def do(self, data: P2URLPreviewGet) -> P2URLPreviewGetResponse:
        return self.f(data)
