class ProxyException(Exception):
    pass


class ProxyTimeoutError(ProxyException, TimeoutError):
    pass


class ProxyConnectionError(ProxyException, OSError):
    pass


class ProxyError(ProxyException):
    def __init__(self, message, error_code=None):
        super().__init__(message)
        self.error_code = error_code
