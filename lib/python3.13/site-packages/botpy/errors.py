# -*- coding: utf-8 -*-


class AuthenticationFailedError(RuntimeError):
    def __init__(self, msg):
        self.msgs = msg

    def __str__(self):
        return self.msgs


class NotFoundError(RuntimeError):
    def __init__(self, msg):
        self.msgs = msg

    def __str__(self):
        return self.msgs


class MethodNotAllowedError(RuntimeError):
    def __init__(self, msg):
        self.msgs = msg

    def __str__(self):
        return self.msgs


class SequenceNumberError(RuntimeError):
    def __init__(self, msg):
        self.msgs = msg

    def __str__(self):
        return self.msgs


class ServerError(RuntimeError):
    def __init__(self, msg):
        self.msgs = msg

    def __str__(self):
        return self.msgs


class ForbiddenError(RuntimeError):
    def __init__(self, msg):
        self.msgs = msg

    def __str__(self):
        return self.msgs


HttpErrorDict = {
    401: AuthenticationFailedError,
    404: NotFoundError,
    405: MethodNotAllowedError,
    403: ForbiddenError,
    429: SequenceNumberError,
    500: ServerError,
    504: ServerError,
}
