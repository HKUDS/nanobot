class SocketIOError(Exception):
    pass


class ConnectionError(SocketIOError):
    pass


class ConnectionRefusedError(ConnectionError):
    """Connection refused exception.

    This exception can be raised from a connect handler when the connection
    is not accepted. The positional arguments provided with the exception are
    returned with the error packet to the client.
    """
    def __init__(self, *args):
        if len(args) == 0:
            self.error_args = {'message': 'Connection rejected by server'}
        elif len(args) == 1:
            self.error_args = {'message': str(args[0])}
        else:
            self.error_args = {'message': str(args[0])}
            if len(args) == 2:
                self.error_args['data'] = args[1]
            else:
                self.error_args['data'] = args[1:]


class TimeoutError(SocketIOError):
    pass


class BadNamespaceError(SocketIOError):
    pass


class DisconnectedError(SocketIOError):
    pass
