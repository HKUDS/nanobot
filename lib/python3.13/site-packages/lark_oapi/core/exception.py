class NoAuthorizationException(Exception):
    def __init__(self, msg: str):
        self.msg: str = msg


class ObtainAccessTokenException(Exception):
    def __init__(self, desc: str, code: int, msg: str):
        self.desc = desc
        self.code = code
        self.msg = msg

    def __str__(self):
        return f"{self.desc}, code: {self.code}, msg: {self.msg}"


class UnmarshalException(Exception):
    def __init__(self, dst, src, field):
        self.dst = dst
        self.src = src
        self.field = field

    def __str__(self):
        return f"expected {self.dst} but was {self.src} at field: {self.field}"


class InvalidArgsException(Exception):
    def __init__(self, msg: str):
        self.msg: str = msg


class AccessDeniedException(Exception):
    def __init__(self, msg: str):
        self.msg: str = msg


class EventException(Exception):
    def __init__(self, msg: str):
        self.msg: str = msg


class CardException(Exception):
    def __init__(self, msg: str):
        self.msg: str = msg
