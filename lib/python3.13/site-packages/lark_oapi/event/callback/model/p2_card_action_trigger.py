from typing import Any, Optional, Union, Dict, List, Set, IO, Callable, Type
from lark_oapi.core.construct import init
from lark_oapi.event.context import EventContext


class CallBackOperator(object):
    _types = {
        "tenant_key": str,
        "user_id": str,
        "open_id": str,
        "union_id": str,
    }

    def __init__(self, d=None):
        self.tenant_key: Optional[str] = None
        self.user_id: Optional[str] = None
        self.open_id: Optional[str] = None
        self.union_id: Optional[str] = None
        init(self, d, self._types)


class CallBackContext(object):
    _types = {
        "url": str,
        "preview_token": str,
        "open_message_id": str,
        "open_chat_id": str,
    }

    def __init__(self, d=None):
        self.url: Optional[str] = None
        self.preview_token: Optional[str] = None
        self.open_message_id: Optional[str] = None
        self.open_chat_id: Optional[str] = None
        init(self, d, self._types)


class CallBackAction(object):
    _types = {
        "value": Dict[str, Any],
        "tag": str,
        "option": str,
        "timezone": str,
        "name": str,
        "form_value": Dict[str, Any],
        "input_value": str,
        "options": List[str],
        "checked": bool,
    }

    def __init__(self, d=None):
        self.value: Optional[Dict[str, Any]] = None
        self.tag: Optional[str] = None
        self.option: Optional[str] = None
        self.timezone: Optional[str] = None
        self.name: Optional[str] = None
        self.form_value: Optional[Dict[str, Any]] = None
        self.input_value: Optional[str] = None
        self.options: Optional[List[str]] = None
        self.checked: Optional[bool] = None
        init(self, d, self._types)


class P2CardActionTriggerData(object):
    _types = {
        "operator": CallBackOperator,
        "token": str,
        "action": CallBackAction,
        "host": str,
        "delivery_type": str,
        "context": CallBackContext,
    }

    def __init__(self, d=None):
        self.operator: Optional[CallBackOperator] = None
        self.token: Optional[str] = None
        self.action: Optional[CallBackAction] = None
        self.host: Optional[str] = None
        self.delivery_type: Optional[str] = None
        self.context: Optional[CallBackContext] = None
        init(self, d, self._types)


class P2CardActionTrigger(EventContext):
    _types = {
        "event": P2CardActionTriggerData
    }

    def __init__(self, d=None):
        super().__init__(d)
        self._types.update(super()._types)
        self.event: Optional[P2CardActionTriggerData] = None
        init(self, d, self._types)


class CallBackToast(object):
    _types = {
        "type": str,
        "content": str,
        "i18n": Dict[str, str],
    }

    def __init__(self, d=None):
        self.type: Optional[str] = None
        self.content: Optional[str] = None
        self.i18n: Optional[Dict[str, str]] = None
        init(self, d, self._types)


class CallBackCard(object):
    _types = {
        "type": str,
        "data": Any,
    }

    def __init__(self, d=None):
        self.type: Optional[str] = None
        self.data: Optional[Any] = None
        init(self, d, self._types)


class P2CardActionTriggerResponse(object):
    _types = {
        "toast": CallBackToast,
        "card": CallBackCard,
    }

    def __init__(self, d=None):
        self.toast: Optional[CallBackToast] = None
        self.card: Optional[CallBackCard] = None
        init(self, d, self._types)
