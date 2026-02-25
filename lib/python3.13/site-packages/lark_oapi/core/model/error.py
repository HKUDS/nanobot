from typing import *

from lark_oapi.core.construct import init


class ErrorDetail(object):
    _types = {
        "key": str,
        "value": str,
    }

    def __init__(self, d=None):
        self.key: Optional[str] = None
        self.value: Optional[str] = None
        init(self, d, self._types)


class ErrorPermissionViolation(object):
    _types = {
        "type": str,
        "subject": str,
        "description": str,
    }

    def __init__(self, d=None):
        self.type: Optional[str] = None
        self.subject: Optional[str] = None
        self.description: Optional[str] = None
        init(self, d, self._types)


class ErrorFieldViolation(object):
    _types = {
        "field": str,
        "value": str,
        "description": str,
    }

    def __init__(self, d=None):
        self.field: Optional[str] = None
        self.value: Optional[str] = None
        self.description: Optional[str] = None
        init(self, d, self._types)


class ErrorHelp(object):
    _types = {
        "url": str,
        "description": str,
    }

    def __init__(self, d=None):
        self.url: Optional[str] = None
        self.description: Optional[str] = None
        init(self, d, self._types)


class Error(object):
    _types = {
        "log_id": str,
        "troubleshooter": str,
        "details": List[ErrorDetail],
        "permission_violations": List[ErrorPermissionViolation],
        "field_violations": List[ErrorFieldViolation],
        "helps": List[ErrorHelp],
    }

    def __init__(self, d=None):
        self.log_id: Optional[str] = None
        self.troubleshooter: Optional[str] = None
        self.details: Optional[List[ErrorDetail]] = None
        self.permission_violations: Optional[List[ErrorPermissionViolation]] = None
        self.field_violations: Optional[List[ErrorFieldViolation]] = None
        self.helps: Optional[List[ErrorHelp]] = None
        init(self, d, self._types)
