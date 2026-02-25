from typing import Any, Optional, Union, Dict, List, Set, IO, Callable, Type
from lark_oapi.core.construct import init
from lark_oapi.event.context import EventContext
from lark_oapi.event.callback.model.p2_card_action_trigger import CallBackOperator, CallBackContext, CallBackCard


class P2URLPreviewGetData(object):
    _types = {
        "operator": CallBackOperator,
        "host": str,
        "context": CallBackContext,
    }

    def __init__(self, d=None):
        self.operator: Optional[CallBackOperator] = None
        self.host: Optional[str] = None
        self.context: Optional[CallBackContext] = None
        init(self, d, self._types)


class P2URLPreviewGet(EventContext):
    _types = {
        "event": P2URLPreviewGetData,
    }

    def __init__(self, d=None):
        super().__init__(d)
        self._types.update(super()._types)
        self.event: Optional[P2URLPreviewGetData] = None
        init(self, d, self._types)


class URLPreviewGetInlineURL(object):
    _types = {
        "copy_url": str,
        "ios": str,
        "android": str,
        "pc": str,
        "web": str,
    }

    def __init__(self, d=None):
        self.copy_url: Optional[str] = None
        self.ios: Optional[str] = None
        self.android: Optional[str] = None
        self.pc: Optional[str] = None
        self.web: Optional[str] = None
        init(self, d, self._types)


class URLPreviewGetInline(object):
    _types = {
        "title": str,
        "i18n_title": Dict[str, str],
        "image_key": str,
        "url": URLPreviewGetInlineURL,
    }

    def __init__(self, d=None):
        self.title: Optional[str] = None
        self.i18n_title: Optional[Dict[str, str]] = None
        self.image_key: Optional[str] = None
        self.url: Optional[URLPreviewGetInlineURL] = None
        init(self, d, self._types)


class P2URLPreviewGetResponse(object):
    _types = {
        "inline": URLPreviewGetInline,
        "card": CallBackCard,
    }

    def __init__(self, d=None):
        self.inline: Optional[URLPreviewGetInline] = None
        self.card: Optional[CallBackCard] = None
        init(self, d, self._types)
