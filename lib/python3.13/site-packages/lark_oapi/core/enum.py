from enum import Enum, auto


class AppType(Enum):
    SELF = auto()
    ISV = auto()


class HttpMethod(Enum):
    GET = auto()
    HEAD = auto()
    POST = auto()
    PUT = auto()
    PATCH = auto()
    DELETE = auto()
    CONNECT = auto()
    OPTIONS = auto()
    TRACE = auto()


class LogLevel(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class AccessTokenType(Enum):
    TENANT = auto()
    APP = auto()
    USER = auto()
