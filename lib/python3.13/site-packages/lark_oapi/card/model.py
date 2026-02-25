from typing import Dict, Optional, Any, List

from lark_oapi.core.construct import init
from lark_oapi.core.model import RawRequest


class Action(object):
    _types = {}

    def __init__(self, d=None) -> None:
        self.value: Dict[str, Any] = {}
        self.tag: Optional[str] = None
        self.option: Optional[str] = None
        self.timezone: Optional[str] = None
        self.name: Optional[str] = None
        self.form_value: Dict[str, Any] = {}
        self.input_value: Optional[str] = None
        self.options: Optional[List[str]] = []
        self.checked: Optional[bool] = None
        init(self, d, self._types)


class Card(object):
    _types = {
        "action": Action
    }

    def __init__(self, d=None) -> None:
        self.open_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.tenant_key: Optional[str] = None
        self.open_message_id: Optional[str] = None
        self.open_chat_id: Optional[str] = None
        self.token: Optional[str] = None
        self.challenge: Optional[str] = None
        self.type: Optional[str] = None
        self.action: Optional[Action] = None
        self.raw: Optional[RawRequest] = None
        init(self, d, self._types)
