import simple_websocket


class SimpleWebSocketWSGI:  # pragma: no cover
    """
    This wrapper class provides a threading WebSocket interface that is
    compatible with eventlet's implementation.
    """
    def __init__(self, handler, server, **kwargs):
        self.app = handler
        self.server_args = kwargs

    def __call__(self, environ, start_response):
        self.ws = simple_websocket.Server(environ, **self.server_args)
        ret = self.app(self)
        if self.ws.mode == 'gunicorn':
            raise StopIteration()
        return ret

    def close(self):
        if self.ws.connected:
            self.ws.close()

    def send(self, message):
        try:
            return self.ws.send(message)
        except simple_websocket.ConnectionClosed:
            raise OSError()

    def wait(self):
        try:
            return self.ws.receive()
        except simple_websocket.ConnectionClosed:
            return None
