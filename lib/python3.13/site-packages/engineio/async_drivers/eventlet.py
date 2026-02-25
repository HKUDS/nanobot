from eventlet.green.threading import Event
from eventlet import queue, sleep, spawn
from eventlet.websocket import WebSocketWSGI as _WebSocketWSGI


class EventletThread:  # pragma: no cover
    """Thread class that uses eventlet green threads.

    Eventlet's own Thread class has a strange bug that causes _DummyThread
    objects to be created and leaked, since they are never garbage collected.
    """
    def __init__(self, target, args=None, kwargs=None):
        self.target = target
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.g = None

    def start(self):
        self.g = spawn(self.target, *self.args, **self.kwargs)

    def join(self):
        if self.g:
            return self.g.wait()


class WebSocketWSGI(_WebSocketWSGI):  # pragma: no cover
    def __init__(self, handler, server):
        try:
            super().__init__(
                handler, max_frame_length=int(server.max_http_buffer_size))
        except TypeError:  # pragma: no cover
            # older versions of eventlet do not support a max frame size
            super().__init__(handler)
        self._sock = None

    def __call__(self, environ, start_response):
        if 'eventlet.input' not in environ:
            raise RuntimeError('You need to use the eventlet server. '
                               'See the Deployment section of the '
                               'documentation for more information.')
        self._sock = environ['eventlet.input'].get_socket()
        return super().__call__(environ, start_response)


_async = {
    'thread': EventletThread,
    'queue': queue.Queue,
    'queue_empty': queue.Empty,
    'event': Event,
    'websocket': WebSocketWSGI,
    'sleep': sleep,
}
