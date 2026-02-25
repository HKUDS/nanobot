class EngineIOError(Exception):
    pass


class ContentTooLongError(EngineIOError):
    pass


class UnknownPacketError(EngineIOError):
    pass


class QueueEmpty(EngineIOError):
    pass


class SocketIsClosedError(EngineIOError):
    pass


class ConnectionError(EngineIOError):
    pass
